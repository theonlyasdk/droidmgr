"""Binary XML parsing for APK manifests and drawable definitions."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from .apk_format import (
    ATTR_COLOR, ATTR_DRAWABLE, ATTR_ICON, ATTR_INSET, ATTR_NAME,
    ATTR_ROUND_ICON, RES_STRING_POOL_TYPE, RES_XML_END_ELEMENT_TYPE,
    RES_XML_RESOURCE_MAP_TYPE, RES_XML_START_ELEMENT_TYPE, RES_XML_TYPE,
    TYPE_DYNAMIC_REFERENCE, TYPE_FLOAT, TYPE_INT_DEC, TYPE_INT_HEX,
    TYPE_NULL, TYPE_REFERENCE, TYPE_ATTRIBUTE, TYPE_STRING, UTF8_FLAG,
    ManifestIcons, TypedValue, _chunk_iter, _is_app_resource, _s32, _u16, _u32,
)


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
