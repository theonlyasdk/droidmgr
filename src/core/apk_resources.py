"""resources.arsc table parsing and icon path selection."""

from __future__ import annotations

import posixpath
from typing import Dict, Iterable, List, Optional, Tuple
from .apk_format import (
    DENSITY_ANY, DENSITY_DEFAULT, DENSITY_NONE, FLAG_COMPACT, FLAG_COMPLEX,
    FLAG_OFFSET16, FLAG_SPARSE, NO_ENTRY, RES_STRING_POOL_TYPE,
    RES_TABLE_PACKAGE_TYPE, RES_TABLE_TYPE, RES_TABLE_TYPE_TYPE, TYPE_STRING,
    ResourceTable, ResourceValue, TypedValue, _chunk_iter, _u16, _u32,
)
from .apk_binxml import StringPool, _parse_res_value


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
