"""ADBManager mixin: APK icon rendering plus the device-APK archive helper."""

import hashlib
import io
import os
import posixpath
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from . import apk_icon
from .adb_icons import _looks_like_unzip_error

if TYPE_CHECKING:
    from .adb_manager import ADBManager


class _ApkRenderMixin:
    """_ApkRenderMixin for ADBManager (see adb_manager.py)."""

    def _render_icon_from_resources(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        res_ids: List[int],
        destination: str,
    ) -> bool:
        all_entries = archive.all_entries()
        for res_id in res_ids:
            rasters, xmls, color, name = apk_icon.pick_paths_for_icon(table, res_id)
            if name:
                guessed = apk_icon.guess_paths_from_name(all_entries, name[0], name[1])
                rasters = apk_icon.sort_raster_paths(
                    rasters + [path for path in guessed if apk_icon._is_raster_path(path)]
                )
                xmls = list(dict.fromkeys(
                    xmls + [path for path in guessed if apk_icon._is_xml_path(path)]
                ))
            for path in rasters:
                data = archive.read_name(path)
                if data and apk_icon.decode_to_png(data, destination):
                    return True
            for xml_path in xmls:
                xml_data = archive.read_name(xml_path)
                if not xml_data:
                    continue
                drawable = apk_icon.parse_xml_drawable(xml_data)
                if drawable and self._render_xml_drawable(archive, table, drawable, destination, color):
                    return True
            if color and apk_icon.composite_adaptive_icon(None, None, color, destination):
                return True
        return False

    def _render_xml_drawable(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        drawable: apk_icon.XmlDrawable,
        destination: str,
        fallback_color: Optional[tuple] = None,
    ) -> bool:
        if drawable.kind == 'adaptive':
            fg_bytes, fg_color = self._resolve_drawable_layer(archive, table, drawable.foreground)
            bg_bytes, bg_color = self._resolve_drawable_layer(archive, table, drawable.background)
            background_color = bg_color or fallback_color
            if not fg_bytes and not bg_bytes and not background_color:
                return False
            return apk_icon.composite_adaptive_icon(
                fg_bytes, bg_bytes, background_color, destination, inset=drawable.inset,
            )
        layer_bytes, layer_color = self._resolve_drawable_layer(archive, table, drawable)
        if layer_bytes:
            return apk_icon.decode_to_png(layer_bytes, destination)
        if layer_color:
            return apk_icon.composite_adaptive_icon(None, None, layer_color, destination)
        return False

    def _resolve_drawable_layer(
        self,
        archive: '_DeviceApkArchive',
        table: apk_icon.ResourceTable,
        layer: Optional[apk_icon.XmlDrawable],
    ) -> Tuple[Optional[bytes], Optional[tuple]]:
        if layer is None:
            return None, None
        if layer.color:
            return None, layer.color
        if not layer.reference:
            return None, None
        rasters, xmls, color, name = apk_icon.pick_paths_for_icon(table, layer.reference)
        if name:
            guessed = apk_icon.guess_paths_from_name(archive.all_entries(), name[0], name[1])
            rasters = apk_icon.sort_raster_paths(
                rasters + [path for path in guessed if apk_icon._is_raster_path(path)]
            )
        for path in rasters:
            data = archive.read_name(path)
            if data:
                return data, color
        return None, color

    def _render_icon_from_filename_fallback(self, archive: '_DeviceApkArchive', destination: str) -> bool:
        preferred = (
            'ic_launcher', 'ic_launcher_round', 'launcher_icon', 'app_icon', 'icon', 'appicon',
        )
        layer_names = ('ic_launcher_foreground', 'ic_launcher_background')
        rasters: List[Tuple[int, str]] = []
        layers: Dict[str, List[str]] = {name: [] for name in layer_names}
        for entry in archive.all_entries():
            lowered = entry.lower()
            if not lowered.startswith('res/'):
                continue
            if not apk_icon._is_raster_path(lowered):
                continue
            folder = posixpath.basename(posixpath.dirname(lowered))
            if not (folder.startswith('mipmap') or folder.startswith('drawable')):
                continue
            stem = posixpath.splitext(posixpath.basename(lowered))[0]
            if any(part in stem for part in ('notification', 'monochrome', 'shortcut', 'tvbanner')):
                continue
            if stem in layer_names:
                layers[stem].append(entry)
                continue
            if stem not in preferred:
                continue
            score = 80 if folder.startswith('mipmap') else 40
            score += preferred.index(stem) * -5
            score += apk_icon._density_from_path(lowered)
            rasters.append((score, entry))
        rasters.sort(key=lambda row: row[0], reverse=True)
        for _, path in rasters:
            data = archive.read_name(path)
            if data and apk_icon.decode_to_png(data, destination):
                return True
        fg_paths = apk_icon.sort_raster_paths(layers['ic_launcher_foreground'])
        bg_paths = apk_icon.sort_raster_paths(layers['ic_launcher_background'])
        fg = archive.read_name(fg_paths[0]) if fg_paths else None
        bg = archive.read_name(bg_paths[0]) if bg_paths else None
        if fg or bg:
            return apk_icon.composite_adaptive_icon(fg, bg, (255, 255, 255, 255), destination)
        return False

    def _list_apk_zip_entries(self, device_id: str, apk_path: str) -> List[str]:
        try:
            listing = self._run_exec_out(
                ['sh', '-c', 'unzip -l -- "$1"', 'droidmgr', apk_path],
                device_id,
            )
            text = listing.decode('utf-8', errors='replace')
            entries = self._parse_unzip_list(text)
            if entries:
                return entries
        except Exception:
            pass
        try:
            listing = self._run_command(['shell', 'unzip', '-l', apk_path], device_id)
            entries = self._parse_unzip_list(listing)
            if entries:
                return entries
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_unzip_list(listing: str) -> List[str]:
        entries: List[str] = []
        seen_header = False
        for line in listing.splitlines():
            stripped = line.strip()
            if not seen_header:
                if stripped.lower().endswith('name') and 'length' in stripped.lower():
                    seen_header = True
                continue
            if not stripped or stripped.startswith('-') or stripped.lower().endswith('files'):
                continue
            match = re.match(r'^\s*\d+\s+\S+\s+\S+\s+(.+)$', line)
            if not match:
                continue
            name = match.group(1).strip()
            if name and posixpath.normpath(name) == name and '..' not in name.split('/'):
                entries.append(name)
        return entries

    def _read_apk_zip_entry(
        self,
        device_id: str,
        apk_path: str,
        entry: str,
        archive: '_DeviceApkArchive',
    ) -> Optional[bytes]:
        if archive.has_local(apk_path):
            return archive.read_local(apk_path, entry)
        try:
            data = self._run_exec_out(
                ['sh', '-c', 'unzip -p -- "$1" "$2"', 'droidmgr', apk_path, entry],
                device_id,
            )
            if data and not _looks_like_unzip_error(data):
                return data
        except Exception:
            pass
        try:
            local_apk = archive.ensure_local(apk_path)
            return archive.read_local(apk_path, entry) if local_apk else None
        except Exception:
            return None



class _DeviceApkArchive:
    """Lists and reads zip entries from on-device APKs, pulling locally if unzip is missing."""

    def __init__(self, adb: ADBManager, device_id: str, apk_paths: List[str]):
        self.adb = adb
        self.device_id = device_id
        self.apk_paths = apk_paths
        self._entries: Dict[str, List[str]] = {}
        self._local: Dict[str, str] = {}
        self._tmp: Optional[str] = None

    def entries(self, apk_path: str) -> List[str]:
        if apk_path not in self._entries:
            listed = self.adb._list_apk_zip_entries(self.device_id, apk_path)
            if not listed:
                local = self.ensure_local(apk_path)
                if local:
                    listed = self._list_local(local)
            self._entries[apk_path] = listed
        return self._entries[apk_path]

    def all_entries(self) -> List[str]:
        found: List[str] = []
        for apk_path in self.apk_paths:
            found.extend(self.entries(apk_path))
        return found

    def read(self, apk_path: str, entry: str) -> Optional[bytes]:
        names = self.entries(apk_path)
        if names and entry not in names:
            return None
        return self.adb._read_apk_zip_entry(self.device_id, apk_path, entry, self)

    def read_name(self, entry: str) -> Optional[bytes]:
        for apk_path in self.apk_paths:
            names = self.entries(apk_path)
            if names and entry not in names:
                continue
            data = self.read(apk_path, entry)
            if data:
                return data
        return None

    def has_local(self, apk_path: str) -> bool:
        return apk_path in self._local

    def ensure_local(self, apk_path: str) -> Optional[str]:
        import tempfile
        if apk_path in self._local and os.path.isfile(self._local[apk_path]):
            return self._local[apk_path]
        if self._tmp is None:
            self._tmp = tempfile.mkdtemp(prefix='droidmgr_apk_')
        local = os.path.join(
            self._tmp,
            hashlib.sha256(apk_path.encode('utf-8')).hexdigest()[:16] + '.apk',
        )
        self.adb.download_file(self.device_id, apk_path, local)
        if os.path.isfile(local) and os.path.getsize(local) > 0:
            self._local[apk_path] = local
            return local
        return None

    def read_local(self, apk_path: str, entry: str) -> Optional[bytes]:
        import zipfile
        local = self._local.get(apk_path)
        if not local:
            return None
        try:
            with zipfile.ZipFile(local, 'r') as zf:
                return zf.read(entry)
        except Exception:
            return None

    @staticmethod
    def _list_local(local_apk: str) -> List[str]:
        import zipfile
        try:
            with zipfile.ZipFile(local_apk, 'r') as zf:
                return [name for name in zf.namelist() if not name.endswith('/')]
        except Exception:
            return []

    def close(self) -> None:
        import shutil
        if self._tmp and os.path.isdir(self._tmp):
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._local.clear()
        self._tmp = None
