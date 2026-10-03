"""Resolve launcher icons from APK binary XML and resources.arsc.

Desktop ADB cannot call PackageManager.loadIcon(), so this mirrors the
framework path: read android:icon from the manifest, resolve it through the
resource table (including split APKs), and composite adaptive-icon layers.
"""

from __future__ import annotations

import io
import posixpath
import struct
import os
import re
import hashlib
import zipfile
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Dict, Iterable, List, Optional, Tuple, Any, Union

# Chunk types
RES_NULL_TYPE = 0x0000
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202

# Attribute resource IDs
ATTR_NAME = 0x01010003
ATTR_ICON = 0x01010002
ATTR_ROUND_ICON = 0x0101052C
ATTR_DRAWABLE = 0x01010199
ATTR_COLOR = 0x010101A5
ATTR_INSET = 0x010101B5

TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_DYNAMIC_REFERENCE = 0x07
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12
TYPE_INT_COLOR_ARGB8 = 0x1C
TYPE_INT_COLOR_RGB8 = 0x1D
TYPE_INT_COLOR_ARGB4 = 0x1E
TYPE_INT_COLOR_RGB4 = 0x1F

UTF8_FLAG = 1 << 8
NO_ENTRY = 0xFFFFFFFF
FLAG_COMPLEX = 0x0001
FLAG_COMPACT = 0x0008
FLAG_SPARSE = 0x01
FLAG_OFFSET16 = 0x02

DENSITY_DEFAULT = 0
DENSITY_ANY = 0xFFFE
DENSITY_NONE = 0xFFFF

ANDROID_PACKAGE_ID = 0x01
APP_PACKAGE_ID = 0x7F

ReadEntry = Callable[[str], Optional[bytes]]


@dataclass
class TypedValue:
    data_type: int
    data: int
    string: Optional[str] = None

    @property
    def is_reference(self) -> bool:
        return self.data_type in (TYPE_REFERENCE, TYPE_ATTRIBUTE, TYPE_DYNAMIC_REFERENCE)

    @property
    def is_color(self) -> bool:
        return TYPE_INT_COLOR_ARGB8 <= self.data_type <= TYPE_INT_COLOR_RGB4

    def as_color(self) -> Optional[Tuple[int, int, int, int]]:
        if not self.is_color:
            return None
        value = self.data & 0xFFFFFFFF
        if self.data_type == TYPE_INT_COLOR_RGB8:
            return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 255)
        if self.data_type == TYPE_INT_COLOR_ARGB4:
            a = (value >> 12) & 0xF
            r = (value >> 8) & 0xF
            g = (value >> 4) & 0xF
            b = value & 0xF
            return (r * 17, g * 17, b * 17, a * 17)
        if self.data_type == TYPE_INT_COLOR_RGB4:
            r = (value >> 8) & 0xF
            g = (value >> 4) & 0xF
            b = value & 0xF
            return (r * 17, g * 17, b * 17, 255)
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, (value >> 24) & 0xFF)


@dataclass
class ManifestIcons:
    application_icon: Optional[int] = None
    application_round_icon: Optional[int] = None
    launcher_icon: Optional[int] = None
    launcher_round_icon: Optional[int] = None

    def candidate_ids(self) -> List[int]:
        ids: List[int] = []
        for value in (
            self.launcher_icon,
            self.application_icon,
            self.launcher_round_icon,
            self.application_round_icon,
        ):
            if value and value not in ids and _is_app_resource(value):
                ids.append(value)
        return ids


@dataclass
class ResourceValue:
    res_id: int
    type_name: str
    key_name: str
    density: int
    value: TypedValue


@dataclass
class ResourceTable:
    values: Dict[int, List[ResourceValue]] = field(default_factory=dict)

    def add(self, item: ResourceValue) -> None:
        self.values.setdefault(item.res_id, []).append(item)

    def merge(self, other: 'ResourceTable') -> None:
        for res_id, items in other.values.items():
            self.values.setdefault(res_id, []).extend(items)

    def name_of(self, res_id: int) -> Optional[Tuple[str, str]]:
        items = self.values.get(res_id)
        if not items:
            return None
        return items[0].type_name, items[0].key_name


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from('<H', data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def _s32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<i', data, offset)[0]


def _is_app_resource(res_id: int) -> bool:
    package = (res_id >> 24) & 0xFF
    return package == APP_PACKAGE_ID or package >= 0x7F


def _chunk_iter(data: bytes, start: int = 0, end: Optional[int] = None) -> Iterable[Tuple[int, int, int, int]]:
    limit = len(data) if end is None else end
    offset = start
    while offset + 8 <= limit:
        chunk_type = _u16(data, offset)
        header_size = _u16(data, offset + 2)
        size = _u32(data, offset + 4)
        if size < 8 or offset + size > limit:
            break
        yield offset, chunk_type, header_size, size
        if size == 0:
            break
        offset += size
