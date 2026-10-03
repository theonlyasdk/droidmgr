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


class StringPool:
    def __init__(self, data: bytes, offset: int = 0):
        self.strings: List[str] = []
        if offset + 28 > len(data):
            return
        chunk_type = _u16(data, offset)
        size = _u32(data, offset + 4)
        if chunk_type != RES_STRING_POOL_TYPE or offset + size > len(data):
            return
        string_count = _u32(data, offset + 8)
        flags = _u32(data, offset + 16)
        strings_start = _u32(data, offset + 20)
        utf8 = bool(flags & UTF8_FLAG)
        if offset + 28 + string_count * 4 > len(data):
            return
        for index in range(string_count):
            str_offset = _u32(data, offset + 28 + index * 4)
            abs_offset = offset + strings_start + str_offset
            try:
                self.strings.append(self._decode(data, abs_offset, utf8))
            except Exception:
                self.strings.append('')

    def get(self, index: int) -> str:
        if index < 0 or index >= len(self.strings):
            return ''
        return self.strings[index]

    @staticmethod
    def _decode_length_utf8(data: bytes, offset: int) -> Tuple[int, int]:
        if offset >= len(data):
            return 0, offset
        first = data[offset]
        if first & 0x80:
            if offset + 1 >= len(data):
                return 0, offset + 1
            return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
        return first, offset + 1

    @staticmethod
    def _decode_length_utf16(data: bytes, offset: int) -> Tuple[int, int]:
        if offset + 2 > len(data):
            return 0, offset
        first = _u16(data, offset)
        if first & 0x8000:
            if offset + 4 > len(data):
                return 0, offset + 2
            return ((first & 0x7FFF) << 16) | _u16(data, offset + 2), offset + 4
        return first, offset + 2

    def _decode(self, data: bytes, offset: int, utf8: bool) -> str:
        if utf8:
            _, offset = self._decode_length_utf8(data, offset)
            byte_len, offset = self._decode_length_utf8(data, offset)
            end = min(len(data), offset + byte_len)
            return data[offset:end].decode('utf-8', errors='replace')
        char_len, offset = self._decode_length_utf16(data, offset)
        end = min(len(data), offset + char_len * 2)
        return data[offset:end].decode('utf-16-le', errors='replace')


def _parse_res_value(data: bytes, offset: int, string_pool: Optional[StringPool] = None) -> Tuple[TypedValue, int]:
    if offset + 8 > len(data):
        return TypedValue(TYPE_NULL, 0), offset
    size = _u16(data, offset)
    data_type = data[offset + 3]
    raw = _u32(data, offset + 4)
    text = None
    if data_type == TYPE_STRING and string_pool is not None:
        text = string_pool.get(raw)
    consumed = size if size >= 8 else 8
    return TypedValue(data_type, raw, text), offset + consumed


def parse_binary_xml_elements(data: bytes) -> Iterable[Tuple[str, str, Dict[str, TypedValue]]]:
    if len(data) < 8 or _u16(data, 0) != RES_XML_TYPE:
        return
    size = _u32(data, 4)
    body_end = min(len(data), size)
    string_pool: Optional[StringPool] = None
    resource_map: List[int] = []
    for offset, chunk_type, header_size, chunk_size in _chunk_iter(data, 8, body_end):
        if chunk_type == RES_STRING_POOL_TYPE:
            string_pool = StringPool(data, offset)
        elif chunk_type == RES_XML_RESOURCE_MAP_TYPE:
            count = (chunk_size - header_size) // 4
            start = offset + header_size
            resource_map = [
                _u32(data, start + index * 4)
                for index in range(count)
                if start + index * 4 + 4 <= offset + chunk_size
            ]
        elif chunk_type == RES_XML_START_ELEMENT_TYPE:
            if string_pool is None or header_size + 12 > chunk_size:
                continue
            name_idx = _s32(data, offset + 20)
            attr_start = _u16(data, offset + 24)
            attr_size = _u16(data, offset + 26) or 20
            attr_count = _u16(data, offset + 28)
            name = string_pool.get(name_idx)
            attrs: Dict[str, TypedValue] = {}
            base = offset + header_size + attr_start
            for index in range(attr_count):
                entry = base + index * attr_size
                if entry + 20 > offset + chunk_size:
                    break
                attr_name_idx = _s32(data, entry + 4)
                raw_str_idx = _s32(data, entry + 8)
                data_type = data[entry + 15]
                raw = _u32(data, entry + 16)
                text = string_pool.get(raw_str_idx) if raw_str_idx >= 0 else None
                if data_type == TYPE_STRING:
                    text = string_pool.get(raw)
                value = TypedValue(data_type, raw, text)
                attr_name = string_pool.get(attr_name_idx)
                if attr_name:
                    attrs[attr_name] = value
                if 0 <= attr_name_idx < len(resource_map):
                    attrs[f'id:0x{resource_map[attr_name_idx]:08x}'] = value
            yield ('start', name, attrs)
        elif chunk_type == RES_XML_END_ELEMENT_TYPE:
            if string_pool is None:
                continue
            name_idx = _s32(data, offset + 20)
            yield ('end', string_pool.get(name_idx), {})


def _attr(attrs: Dict[str, TypedValue], name: str, attr_id: int) -> Optional[TypedValue]:
    value = attrs.get(name)
    if value is None:
        value = attrs.get(f'id:0x{attr_id:08x}')
    return value


def _attr_ref(attrs: Dict[str, TypedValue], name: str, attr_id: int) -> Optional[int]:
    value = _attr(attrs, name, attr_id)
    if value is None:
        return None
    if value.is_reference and _is_app_resource(value.data):
        return value.data
    return None


def _attr_name(attrs: Dict[str, TypedValue]) -> str:
    value = _attr(attrs, 'name', ATTR_NAME)
    if value is None:
        return ''
    if value.string:
        return value.string
    return ''


def parse_manifest_icons(data: bytes) -> ManifestIcons:
    icons = ManifestIcons()
    in_application = False
    in_launcher_candidate = False
    saw_main = False
    saw_launcher = False
    activity_icon: Optional[int] = None
    activity_round: Optional[int] = None
    for event, name, attrs in parse_binary_xml_elements(data):
        lowered = name.lower()
        if event == 'start':
            if lowered == 'application':
                in_application = True
                icons.application_icon = _attr_ref(attrs, 'icon', ATTR_ICON)
                icons.application_round_icon = _attr_ref(attrs, 'roundIcon', ATTR_ROUND_ICON)
            elif in_application and lowered in ('activity', 'activity-alias'):
                in_launcher_candidate = True
                saw_main = False
                saw_launcher = False
                activity_icon = _attr_ref(attrs, 'icon', ATTR_ICON)
                activity_round = _attr_ref(attrs, 'roundIcon', ATTR_ROUND_ICON)
            elif in_launcher_candidate and lowered == 'action':
                if _attr_name(attrs) == 'android.intent.action.MAIN':
                    saw_main = True
            elif in_launcher_candidate and lowered == 'category':
                if _attr_name(attrs) == 'android.intent.category.LAUNCHER':
                    saw_launcher = True
        elif event == 'end':
            if lowered in ('activity', 'activity-alias') and in_launcher_candidate:
                if saw_main and saw_launcher:
                    if activity_icon and not icons.launcher_icon:
                        icons.launcher_icon = activity_icon
                    if activity_round and not icons.launcher_round_icon:
                        icons.launcher_round_icon = activity_round
                in_launcher_candidate = False
            elif lowered == 'application':
                in_application = False
    return icons


@dataclass
class XmlDrawable:
    kind: str
    reference: Optional[int] = None
    color: Optional[Tuple[int, int, int, int]] = None
    background: Optional['XmlDrawable'] = None
    foreground: Optional['XmlDrawable'] = None
    inset: float = 0.0
    path: Optional[str] = None


def parse_xml_drawable(data: bytes) -> Optional[XmlDrawable]:
    root: Optional[XmlDrawable] = None
    current_layer: Optional[str] = None
    adaptive = XmlDrawable(kind='adaptive')
    for event, name, attrs in parse_binary_xml_elements(data):
        lowered = name.lower()
        if event != 'start':
            if event == 'end' and lowered in ('foreground', 'background'):
                current_layer = None
            continue
        drawable = _parse_drawable_node(lowered, attrs)
        if lowered == 'adaptive-icon':
            root = adaptive
        elif lowered == 'foreground':
            current_layer = 'foreground'
            if drawable:
                adaptive.foreground = drawable
            root = root or adaptive
        elif lowered == 'background':
            current_layer = 'background'
            if drawable:
                adaptive.background = drawable
            root = root or adaptive
        elif lowered == 'monochrome':
            continue
        elif drawable:
            if current_layer == 'foreground':
                adaptive.foreground = drawable
            elif current_layer == 'background':
                adaptive.background = drawable
            elif root is None:
                root = drawable
        if lowered == 'inset' and drawable and drawable.inset and adaptive.foreground is drawable:
            adaptive.inset = drawable.inset
    if adaptive.foreground or adaptive.background:
        return adaptive
    return root


def _parse_drawable_node(name: str, attrs: Dict[str, TypedValue]) -> Optional[XmlDrawable]:
    color_value = _attr(attrs, 'color', ATTR_COLOR)
    drawable_value = _attr(attrs, 'drawable', ATTR_DRAWABLE)
    inset_value = _attr(attrs, 'inset', ATTR_INSET)
    node = XmlDrawable(kind='ref')
    if drawable_value:
        if drawable_value.is_reference:
            node.reference = drawable_value.data
        elif drawable_value.is_color:
            node.kind = 'color'
            node.color = drawable_value.as_color()
    if color_value and color_value.is_color:
        node.kind = 'color'
        node.color = color_value.as_color()
    elif color_value and color_value.is_reference:
        node.reference = color_value.data
    if inset_value and inset_value.data_type == TYPE_FLOAT:
        node.inset = struct.unpack('>f', struct.pack('>I', inset_value.data))[0]
    elif inset_value and inset_value.data_type in (TYPE_INT_DEC, TYPE_INT_HEX):
        node.inset = float(inset_value.data)
    if name == 'color' and node.color:
        node.kind = 'color'
    if node.reference or node.color:
        return node
    return None


def parse_resource_table(data: bytes) -> ResourceTable:
    table = ResourceTable()
    if len(data) < 12 or _u16(data, 0) != RES_TABLE_TYPE:
        return table
    global_strings: Optional[StringPool] = None
    end = min(len(data), _u32(data, 4))
    for offset, chunk_type, _, chunk_size in _chunk_iter(data, 8, end):
        if chunk_type == RES_STRING_POOL_TYPE and global_strings is None:
            global_strings = StringPool(data, offset)
        elif chunk_type == RES_TABLE_PACKAGE_TYPE:
            _parse_package(data, offset, offset + chunk_size, global_strings or StringPool(b''), table)
    return table


def _parse_package(
    data: bytes,
    offset: int,
    end: int,
    global_strings: StringPool,
    table: ResourceTable,
) -> None:
    if offset + 8 + 4 + 256 > len(data):
        return
    header_size = _u16(data, offset + 2)
    package_id = _u32(data, offset + 8)
    type_strings_off = _u32(data, offset + 8 + 4 + 256)
    key_strings_off = _u32(data, offset + 8 + 4 + 256 + 8)
    type_pool = StringPool(data, offset + type_strings_off) if type_strings_off else StringPool(b'')
    key_pool = StringPool(data, offset + key_strings_off) if key_strings_off else StringPool(b'')
    inner_start = offset + header_size
    for chunk_off, chunk_type, chunk_header, chunk_size in _chunk_iter(data, inner_start, end):
        if chunk_type != RES_TABLE_TYPE_TYPE:
            continue
        _parse_type_chunk(
            data, chunk_off, chunk_header, chunk_size, package_id,
            type_pool, key_pool, global_strings, table,
        )


def _parse_type_chunk(
    data: bytes,
    offset: int,
    header_size: int,
    chunk_size: int,
    package_id: int,
    type_pool: StringPool,
    key_pool: StringPool,
    global_strings: StringPool,
    table: ResourceTable,
) -> None:
    if header_size < 20 or offset + 20 > len(data):
        return
    type_id = data[offset + 8]
    flags = data[offset + 9]
    entry_count = _u32(data, offset + 12)
    entries_start = _u32(data, offset + 16)
    type_name = type_pool.get(type_id - 1) if type_id else ''
    density = DENSITY_DEFAULT
    if offset + 20 + 16 <= len(data):
        config_size = _u32(data, offset + 20)
        if config_size >= 16 and offset + 20 + 16 <= offset + header_size:
            density = _u16(data, offset + 20 + 14)

    chunk_end = offset + chunk_size
    if flags & FLAG_SPARSE:
        entries = offset + header_size
        for index in range(entry_count):
            pos = entries + index * 4
            if pos + 4 > chunk_end:
                break
            entry_idx = _u16(data, pos)
            entry_off = _u16(data, pos + 2) * 4
            _parse_entry(
                data, offset + entries_start + entry_off, chunk_end,
                package_id, type_id, entry_idx, type_name, density,
                key_pool, global_strings, table,
            )
        return

    offset_width = 2 if flags & FLAG_OFFSET16 else 4
    table_start = offset + header_size
    for index in range(entry_count):
        pos = table_start + index * offset_width
        if pos + offset_width > chunk_end:
            break
        if offset_width == 2:
            raw = _u16(data, pos)
            if raw == 0xFFFF:
                continue
            entry_off = raw * 4
        else:
            raw = _u32(data, pos)
            if raw == NO_ENTRY:
                continue
            entry_off = raw
        _parse_entry(
            data, offset + entries_start + entry_off, chunk_end,
            package_id, type_id, index, type_name, density,
            key_pool, global_strings, table,
        )


def _parse_entry(
    data: bytes,
    offset: int,
    chunk_end: int,
    package_id: int,
    type_id: int,
    entry_index: int,
    type_name: str,
    density: int,
    key_pool: StringPool,
    global_strings: StringPool,
    table: ResourceTable,
) -> None:
    if offset + 8 > chunk_end:
        return
    flags = _u16(data, offset + 2)
    if flags & FLAG_COMPACT:
        key_index = _u16(data, offset)
        data_type = (flags >> 8) & 0xFF
        raw = _u32(data, offset + 4)
        value = TypedValue(data_type, raw, global_strings.get(raw) if data_type == TYPE_STRING else None)
        key_name = key_pool.get(key_index)
    else:
        key_index = _u32(data, offset + 4)
        key_name = key_pool.get(key_index)
        if flags & FLAG_COMPLEX:
            return
        size = _u16(data, offset)
        value_offset = offset + (size if size >= 8 else 8)
        value, _ = _parse_res_value(data, value_offset, global_strings)
    res_id = ((package_id & 0xFF) << 24) | ((type_id & 0xFF) << 16) | (entry_index & 0xFFFF)
    table.add(ResourceValue(res_id, type_name, key_name, density, value))


def resolve_resource(
    table: ResourceTable,
    res_id: int,
    depth: int = 0,
) -> List[ResourceValue]:
    if depth > 8:
        return []
    items = list(table.values.get(res_id, []))
    resolved: List[ResourceValue] = []
    for item in items:
        if item.value.is_reference and item.value.data:
            nested = resolve_resource(table, item.value.data, depth + 1)
            if nested:
                resolved.extend(nested)
                continue
        resolved.append(item)
    return resolved


def _density_rank(density: int) -> int:
    if density in (DENSITY_ANY, DENSITY_NONE, DENSITY_DEFAULT):
        return 0
    return density


def _is_raster_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith(('.png', '.webp', '.jpg', '.jpeg')) and not lowered.endswith('.9.png')


def _is_xml_path(path: str) -> bool:
    return path.lower().endswith('.xml')


def pick_paths_for_icon(table: ResourceTable, res_id: int) -> Tuple[List[str], List[str], Optional[Tuple[int, int, int, int]], Optional[Tuple[str, str]]]:
    """Return (raster_paths, xml_paths, solid_color, type_and_name)."""
    items = resolve_resource(table, res_id)
    name = table.name_of(res_id)
    rasters: List[Tuple[int, str]] = []
    xmls: List[Tuple[int, str]] = []
    color: Optional[Tuple[int, int, int, int]] = None
    for item in items:
        if item.value.is_color and color is None:
            color = item.value.as_color()
        path = item.value.string or ''
        if not path.startswith('res/'):
            continue
        if _is_xml_path(path):
            xmls.append((_density_rank(item.density), path))
        elif _is_raster_path(path):
            rasters.append((_density_rank(item.density), path))
    rasters.sort(key=lambda row: row[0], reverse=True)
    xmls.sort(key=lambda row: row[0], reverse=True)
    raster_paths = list(dict.fromkeys(path for _, path in rasters))
    xml_paths = list(dict.fromkeys(path for _, path in xmls))
    return raster_paths, xml_paths, color, name


def guess_paths_from_name(entries: Iterable[str], type_name: str, key_name: str) -> List[str]:
    if not key_name:
        return []
    wanted = []
    type_opts = [type_name] if type_name else ['mipmap', 'drawable']
    extra_types = ['mipmap', 'drawable']
    for extra in extra_types:
        if extra not in type_opts:
            type_opts.append(extra)
    for entry in entries:
        lowered = entry.lower()
        if not lowered.startswith('res/'):
            continue
        directory = posixpath.basename(posixpath.dirname(lowered))
        stem = posixpath.splitext(posixpath.basename(lowered))[0]
        if stem != key_name.lower():
            continue
        if not any(directory.startswith(prefix) for prefix in type_opts):
            continue
        wanted.append(entry)
    return wanted


def _density_from_path(path: str) -> int:
    lowered = path.lower()
    mapping = (
        ('xxxhdpi', 640),
        ('xxhdpi', 480),
        ('xhdpi', 320),
        ('hdpi', 240),
        ('tvdpi', 213),
        ('mdpi', 160),
        ('ldpi', 120),
        ('anydpi', 0),
        ('nodpi', 0),
    )
    for name, value in mapping:
        if name in lowered:
            return value
    return 0


def sort_raster_paths(paths: Iterable[str]) -> List[str]:
    unique = list(dict.fromkeys(paths))
    unique.sort(key=_density_from_path, reverse=True)
    return unique


def decode_to_png(data: bytes, destination: str, min_size: int = 24) -> bool:
    try:
        from PIL import Image
    except ImportError:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            with open(destination, 'wb') as handle:
                handle.write(data)
            return True
        return False
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        if image.width < min_size or image.height < min_size:
            return False
        if getattr(image, 'mode', '') == 'P':
            image = image.convert('RGBA')
        else:
            image = image.convert('RGBA')
        if path_is_nine_patch(data):
            image = image.crop((1, 1, image.width - 1, image.height - 1))
        image.save(destination, format='PNG')
        return True
    except Exception:
        return False


def path_is_nine_patch(data: bytes) -> bool:
    return b'npTc' in data[:64] or b'npTc' in data[:256]


def composite_adaptive_icon(
    foreground: Optional[bytes],
    background: Optional[bytes],
    background_color: Optional[Tuple[int, int, int, int]],
    destination: str,
    canvas_size: int = 432,
    inset: float = 0.0,
) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        if foreground:
            return decode_to_png(foreground, destination)
        if background:
            return decode_to_png(background, destination)
        return False

    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    if background_color:
        canvas.paste(background_color, (0, 0, canvas_size, canvas_size))
    if background:
        try:
            bg = Image.open(io.BytesIO(background)).convert('RGBA')
            bg = bg.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
            canvas = Image.alpha_composite(canvas, bg)
        except Exception:
            pass
    if foreground:
        try:
            fg = Image.open(io.BytesIO(foreground)).convert('RGBA')
            if inset:
                inner = max(1, int(canvas_size * (1.0 - min(inset, 0.4))))
                pad = (canvas_size - inner) // 2
                fg = fg.resize((inner, inner), Image.Resampling.LANCZOS)
                layer = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
                layer.paste(fg, (pad, pad), fg)
                canvas = Image.alpha_composite(canvas, layer)
            else:
                fg = fg.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
                canvas = Image.alpha_composite(canvas, fg)
        except Exception:
            pass

    mask = Image.new('L', (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(canvas_size * 0.22)
    draw.rounded_rectangle((0, 0, canvas_size - 1, canvas_size - 1), radius=radius, fill=255)
    canvas.putalpha(mask)
    if max(canvas.size) < 24:
        return False
    canvas.save(destination, format='PNG')
    return True


def parse_icon_resource_ids_from_dumpsys(output: str) -> List[int]:
    ids: List[int] = []
    for line in output.splitlines():
        stripped = line.strip()
        for prefix in ('icon=0x', 'icon=0X', 'roundIcon=0x', 'roundIcon=0X'):
            if stripped.startswith(prefix) or f' {prefix}' in stripped:
                match_at = stripped.lower().find(prefix.lower())
                if match_at < 0:
                    continue
                raw = stripped[match_at:].split('=', 1)[1].split()[0]
                try:
                    value = int(raw, 16) if raw.lower().startswith('0x') else int(raw, 16)
                except ValueError:
                    continue
                if _is_app_resource(value) and value not in ids:
                    ids.append(value)
    return ids


def encode_display_png(source_path: str, destination: str, size: int = 512) -> bool:
    try:
        from PIL import Image
    except ImportError:
        if source_path != destination:
            with open(source_path, 'rb') as src, open(destination, 'wb') as dst:
                dst.write(src.read())
        return True
    try:
        image = Image.open(source_path).convert('RGBA')
        if image.width != size or image.height != size:
            image = image.resize((size, size), Image.Resampling.LANCZOS)
        image.save(destination, format='PNG')
        return True
    except Exception:
        return False


# --- APK Static Inspector (Manifest, Components, Signatures) -----------------

def parse_asn1_length(data: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(data):
        return 0, offset
    first = data[offset]
    if first < 0x80:
        return first, offset + 1
    num_bytes = first & 0x7F
    if offset + 1 + num_bytes > len(data):
        return 0, offset + 1
    val = 0
    for b in data[offset + 1:offset + 1 + num_bytes]:
        val = (val << 8) | b
    return val, offset + 1 + num_bytes


def parse_asn1_tag(data: bytes, offset: int) -> Tuple[Optional[int], int, int]:
    if offset >= len(data):
        return None, 0, offset
    tag = data[offset]
    length, content_offset = parse_asn1_length(data, offset + 1)
    return tag, length, content_offset


def _decode_x509_name(name_bytes: bytes) -> str:
    oids = {
        b'\x55\x04\x03': 'CN',
        b'\x55\x04\x06': 'C',
        b'\x55\x04\x07': 'L',
        b'\x55\x04\x08': 'ST',
        b'\x55\x04\x0a': 'O',
        b'\x55\x04\x0b': 'OU',
        b'\x2a\x86\x48\x86\xf7\x0d\x01\x09\x01': 'EMAIL'
    }
    parts = []
    for oid, label in oids.items():
        pos = name_bytes.find(oid)
        if pos >= 0:
            val_offset = pos + len(oid)
            if val_offset < len(name_bytes):
                _, vl, vcont = parse_asn1_tag(name_bytes, val_offset)
                str_val = name_bytes[vcont:vcont + vl].decode('utf-8', errors='replace')
                if str_val:
                    parts.append(f'{label}={str_val}')
    return ', '.join(parts) if parts else 'Unknown'


def parse_x509_der(cert_bytes: bytes) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        'sha256': ':'.join(f'{b:02X}' for b in hashlib.sha256(cert_bytes).digest()),
        'sha1': ':'.join(f'{b:02X}' for b in hashlib.sha1(cert_bytes).digest()),
        'md5': ':'.join(f'{b:02X}' for b in hashlib.md5(cert_bytes).digest()),
        'serial': 'Unknown',
        'subject': 'Unknown',
        'issuer': 'Unknown',
        'valid_from': '',
        'valid_to': '',
    }
    try:
        _, _, off = parse_asn1_tag(cert_bytes, 0)
        _, _, tbs_off = parse_asn1_tag(cert_bytes, off)
        cur = tbs_off

        if cur < len(cert_bytes) and cert_bytes[cur] == 0xA0:
            _, l, cur = parse_asn1_tag(cert_bytes, cur)
            cur += l  # Skip version

        # Serial number
        _, l, cur = parse_asn1_tag(cert_bytes, cur)
        info['serial'] = cert_bytes[cur:cur + l].hex().upper()
        cur += l

        # Signature algorithm
        _, l, cur = parse_asn1_tag(cert_bytes, cur)
        cur += l

        # Issuer
        _, issuer_len, cur = parse_asn1_tag(cert_bytes, cur)
        info['issuer'] = _decode_x509_name(cert_bytes[cur:cur + issuer_len])
        cur += issuer_len

        # Validity
        _, val_len, cur = parse_asn1_tag(cert_bytes, cur)
        val_bytes = cert_bytes[cur:cur + val_len]
        cur += val_len
        try:
            _, vl1, vo1 = parse_asn1_tag(val_bytes, 0)
            d1 = val_bytes[vo1:vo1 + vl1].decode('ascii', errors='ignore')
            _, vl2, vo2 = parse_asn1_tag(val_bytes, vo1 + vl1)
            d2 = val_bytes[vo2:vo2 + vl2].decode('ascii', errors='ignore')
            info['valid_from'] = d1
            info['valid_to'] = d2
        except Exception:
            pass

        # Subject
        _, subj_len, cur = parse_asn1_tag(cert_bytes, cur)
        info['subject'] = _decode_x509_name(cert_bytes[cur:cur + subj_len])
    except Exception:
        pass

    return info


def find_x509_certs_in_pkcs7(data: bytes) -> List[bytes]:
    certs: List[bytes] = []
    i = 0
    while i < len(data) - 4:
        if data[i] == 0x30:
            cert_len, len_offset = parse_asn1_length(data, i + 1)
            if cert_len > 100 and i + len_offset + cert_len <= len(data):
                sub_i = i + len_offset
                if sub_i < len(data) and data[sub_i] == 0x30:
                    cert_data = data[i:i + len_offset + cert_len]
                    certs.append(cert_data)
                    i += len_offset + cert_len
                    continue
        i += 1
    return certs


def parse_apk_signatures(apk_path: str) -> Dict[str, Any]:
    sig_info: Dict[str, Any] = {
        'schemes': [],
        'certificates': [],
    }
    if not os.path.isfile(apk_path):
        return sig_info

    # 1. Check v1 (JAR signing)
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            meta_sig_files = [
                n for n in zf.namelist()
                if n.upper().startswith('META-INF/') and any(n.upper().endswith(ext) for ext in ('.RSA', '.DSA', '.EC'))
            ]
            if meta_sig_files:
                sig_info['schemes'].append('v1 (JAR)')
                for mf in meta_sig_files:
                    try:
                        raw = zf.read(mf)
                        found_certs = find_x509_certs_in_pkcs7(raw)
                        for c in found_certs:
                            parsed = parse_x509_der(c)
                            parsed['scheme'] = 'v1'
                            parsed['source'] = mf
                            sig_info['certificates'].append(parsed)
                    except Exception:
                        pass
    except Exception:
        pass

    # 2. Check APK Signing Block (v2, v3, v3.1)
    try:
        with open(apk_path, 'rb') as f:
            f.seek(0, 2)
            flen = f.tell()
            f.seek(max(0, flen - 65536))
            tail = f.read()
            idx = tail.rfind(b'PK\x05\x06')
            if idx >= 0:
                cd_offset = struct.unpack('<I', tail[idx + 16:idx + 20])[0]
                if cd_offset >= 24:
                    f.seek(cd_offset - 24)
                    bsize, magic = struct.unpack('<Q16s', f.read(24))
                    if magic == b'APK Sig Block 42':
                        f.seek(cd_offset - bsize)
                        end_of_pairs = cd_offset - 24
                        while f.tell() < end_of_pairs:
                            pair_len = struct.unpack('<Q', f.read(8))[0]
                            pair_id = struct.unpack('<I', f.read(4))[0]
                            pair_val = f.read(pair_len - 4)

                            scheme_label = None
                            if pair_id == 0x7109871a:
                                scheme_label = 'v2'
                                if 'v2' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v2')
                            elif pair_id == 0xf05368c0:
                                scheme_label = 'v3'
                                if 'v3' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v3')
                            elif pair_id == 0x1b93ad61:
                                scheme_label = 'v3.1'
                                if 'v3.1' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v3.1')

                            if scheme_label and len(pair_val) >= 4:
                                try:
                                    pos = 4
                                    while pos < len(pair_val):
                                        signer_len = struct.unpack('<I', pair_val[pos:pos + 4])[0]
                                        signer = pair_val[pos + 4:pos + 4 + signer_len]
                                        pos += 4 + signer_len
                                        sd_len = struct.unpack('<I', signer[0:4])[0]
                                        sd = signer[4:4 + sd_len]
                                        dig_len = struct.unpack('<I', sd[0:4])[0]
                                        c_offset = 4 + dig_len
                                        certs_len = struct.unpack('<I', sd[c_offset:c_offset + 4])[0]
                                        c_pos = c_offset + 4
                                        while c_pos < c_offset + 4 + certs_len:
                                            cert_len = struct.unpack('<I', sd[c_pos:c_pos + 4])[0]
                                            cert_bytes = sd[c_pos + 4:c_pos + 4 + cert_len]
                                            c_pos += 4 + cert_len
                                            parsed = parse_x509_der(cert_bytes)
                                            parsed['scheme'] = scheme_label
                                            sig_info['certificates'].append(parsed)
                                except Exception:
                                    pass
    except Exception:
        pass

    return sig_info


def parse_apk_manifest(manifest_bytes: bytes) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        'package': '',
        'version_name': '',
        'version_code': '',
        'min_sdk': '',
        'target_sdk': '',
        'compile_sdk': '',
        'debuggable': False,
        'permissions': [],
        'activities': [],
        'services': [],
        'receivers': [],
        'providers': [],
    }
    for event, name, attrs in parse_binary_xml_elements(manifest_bytes):
        if event != 'start':
            continue
        tag_low = (name or '').lower()
        if tag_low == 'manifest':
            res['package'] = attrs.get('package', TypedValue(0, 0, '')).string or ''
            vc = attrs.get('versionCode') or attrs.get('id:0x0101021b')
            if vc:
                res['version_code'] = str(vc.data if vc.data_type == TYPE_INT_DEC else (vc.string or vc.data))
            vn = attrs.get('versionName') or attrs.get('id:0x0101021c')
            if vn:
                res['version_name'] = str(vn.string or vn.data)
            cs = attrs.get('compileSdkVersion') or attrs.get('id:0x01010572')
            if cs:
                res['compile_sdk'] = str(cs.data if cs.data_type == TYPE_INT_DEC else (cs.string or cs.data))
        elif tag_low == 'uses-sdk':
            ms = attrs.get('minSdkVersion') or attrs.get('id:0x0101020c')
            if ms:
                res['min_sdk'] = str(ms.data if ms.data_type == TYPE_INT_DEC else (ms.string or ms.data))
            ts = attrs.get('targetSdkVersion') or attrs.get('id:0x01010270')
            if ts:
                res['target_sdk'] = str(ts.data if ts.data_type == TYPE_INT_DEC else (ts.string or ts.data))
        elif tag_low == 'application':
            dbg = attrs.get('debuggable') or attrs.get('id:0x01010000')
            if dbg:
                res['debuggable'] = bool(dbg.data) if dbg.data_type in (TYPE_INT_BOOLEAN, TYPE_INT_DEC) else (str(dbg.string).lower() == 'true')
        elif tag_low == 'uses-permission':
            pname = attrs.get('name') or attrs.get('id:0x01010003')
            if pname and (pname.string or pname.data):
                val = pname.string or str(pname.data)
                if val not in res['permissions']:
                    res['permissions'].append(val)
        elif tag_low in ('activity', 'activity-alias'):
            aname = attrs.get('name') or attrs.get('id:0x01010003')
            if aname and (aname.string or aname.data):
                val = aname.string or str(aname.data)
                if val not in res['activities']:
                    res['activities'].append(val)
        elif tag_low == 'service':
            sname = attrs.get('name') or attrs.get('id:0x01010003')
            if sname and (sname.string or sname.data):
                val = sname.string or str(sname.data)
                if val not in res['services']:
                    res['services'].append(val)
        elif tag_low == 'receiver':
            rname = attrs.get('name') or attrs.get('id:0x01010003')
            if rname and (rname.string or rname.data):
                val = rname.string or str(rname.data)
                if val not in res['receivers']:
                    res['receivers'].append(val)
        elif tag_low == 'provider':
            prname = attrs.get('name') or attrs.get('id:0x01010003')
            if prname and (prname.string or prname.data):
                val = prname.string or str(prname.data)
                if val not in res['providers']:
                    res['providers'].append(val)

    return res


def inspect_apk(apk_path: str) -> Dict[str, Any]:
    """Statically parse a local .apk file without installation or AAPT."""
    out: Dict[str, Any] = {
        'file_path': apk_path,
        'file_size': 0,
        'file_name': os.path.basename(apk_path),
        'dex_count': 0,
        'package': '',
        'version_name': '',
        'version_code': '',
        'min_sdk': '',
        'target_sdk': '',
        'compile_sdk': '',
        'debuggable': False,
        'permissions': [],
        'activities': [],
        'services': [],
        'receivers': [],
        'providers': [],
        'schemes': [],
        'certificates': [],
    }
    if not os.path.isfile(apk_path):
        return out

    out['file_size'] = os.path.getsize(apk_path)

    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            dex_files = [n for n in zf.namelist() if n.endswith('.dex')]
            out['dex_count'] = len(dex_files)
            if 'AndroidManifest.xml' in zf.namelist():
                manifest_bytes = zf.read('AndroidManifest.xml')
                manifest_data = parse_apk_manifest(manifest_bytes)
                out.update(manifest_data)
    except Exception:
        pass

    sig_data = parse_apk_signatures(apk_path)
    out['schemes'] = sig_data.get('schemes', [])
    out['certificates'] = sig_data.get('certificates', [])

    return out
