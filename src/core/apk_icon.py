"""Resolve launcher icons from APK binary XML and resources.arsc.

Desktop ADB cannot call PackageManager.loadIcon(), so this mirrors the
framework path: read android:icon from the manifest, resolve it through the
resource table (including split APKs), and composite adaptive-icon layers.
"""

from __future__ import annotations

import io
import posixpath
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Dict, Iterable, List, Optional, Tuple

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
            name_idx = _s32(data, offset + 16)
            attr_start = _u16(data, offset + 20)
            attr_size = _u16(data, offset + 22) or 20
            attr_count = _u16(data, offset + 24)
            name = string_pool.get(name_idx)
            attrs: Dict[str, TypedValue] = {}
            base = offset + 8 + attr_start
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
            name_idx = _s32(data, offset + 16)
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
