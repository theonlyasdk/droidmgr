"""ADBManager mixin: app icon extraction entry points and cache."""

import hashlib
import os
import posixpath
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from . import apk_icon
from .adb_apps import _validate_package

if TYPE_CHECKING:
    from .adb_apk_render import _DeviceApkArchive


class _IconsMixin:
    """_IconsMixin for ADBManager (see adb_manager.py)."""

    @staticmethod
    def cleanup_icon_cache(output_dir: str, max_age_days: int = 7) -> None:
        """Purge icon files in output_dir older than max_age_days."""
        import time
        try:
            if not os.path.exists(output_dir):
                return
            cutoff = time.time() - (max_age_days * 86400)
            for entry in os.listdir(output_dir):
                filepath = os.path.join(output_dir, entry)
                if os.path.isfile(filepath):
                    try:
                        if os.path.getmtime(filepath) < cutoff:
                            os.remove(filepath)
                    except Exception:
                        pass
        except Exception:
            pass

    def _ensure_icon_extractor(self, device_id: str) -> bool:
        """Ensure icon_extractor.jar is available on device at /data/local/tmp/droidmgr_icon.jar."""
        if not hasattr(self, '_icon_extractor_ready'):
            self._icon_extractor_ready = set()
        if device_id in self._icon_extractor_ready:
            return True

        jar_candidates = [
            Path(__file__).resolve().parent.parent / 'assets' / 'icon_extractor.jar',
            Path(__file__).resolve().parent.parent / 'ui' / 'assets' / 'icon_extractor.jar',
            Path(getattr(sys, '_MEIPASS', '')) / 'assets' / 'icon_extractor.jar',
        ]
        local_jar = None
        for p in jar_candidates:
            if p.is_file():
                local_jar = str(p)
                break
        if not local_jar:
            return False

        try:
            self._run_command(['push', local_jar, '/data/local/tmp/droidmgr_icon.jar'], device_id, timeout=10)
            self._icon_extractor_ready.add(device_id)
            return True
        except Exception:
            return False

    def extract_app_icons_batch(
        self,
        device_id: str,
        packages: List[str],
        output_dir: str,
        cancel_check: Optional[any] = None,
    ) -> Dict[str, str]:
        """Batch extract launcher icons using on-device PackageManager via app_process.
        
        Returns a mapping of {package_name: local_png_path} for all successfully extracted icons.
        """
        results: Dict[str, str] = {}
        if not packages or not device_id:
            return results

        os.makedirs(output_dir, exist_ok=True)
        device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]

        to_fetch = []
        for pkg in packages:
            local_icon_path = os.path.join(output_dir, f"{pkg}_{device_key}_latest_icon.png")
            if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                results[pkg] = local_icon_path
            else:
                to_fetch.append(pkg)

        if not to_fetch or not self._ensure_icon_extractor(device_id):
            return results

        chunk_size = 40
        for i in range(0, len(to_fetch), chunk_size):
            if cancel_check and cancel_check():
                break
            chunk = to_fetch[i:i + chunk_size]
            try:
                cmd = [
                    'shell',
                    'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                    'app_process', '/',
                    'com.droidmgr.IconExtractor',
                    '--out=/data/local/tmp/droidmgr_icons',
                    *chunk
                ]
                out = self._run_command(cmd, device_id, timeout=25)
                succeeded = []
                for line in out.splitlines():
                    if line.startswith("OK:"):
                        parts = line.split(":", 1)
                        if len(parts) > 1:
                            succeeded.append(parts[1].strip())

                if succeeded:
                    staging_dir = tempfile.mkdtemp(prefix='droidmgr_icons_pull_')
                    try:
                        remote_paths = [f"/data/local/tmp/droidmgr_icons/{p}.png" for p in succeeded]
                        try:
                            self._run_command(['pull', *remote_paths, staging_dir], device_id, timeout=15)
                        except Exception:
                            for p in succeeded:
                                try:
                                    self._run_command(['pull', f'/data/local/tmp/droidmgr_icons/{p}.png', os.path.join(staging_dir, f"{p}.png")], device_id, timeout=5)
                                except Exception:
                                    pass

                        for pkg_ok in succeeded:
                            if cancel_check and cancel_check():
                                break
                            staged_file = os.path.join(staging_dir, f"{pkg_ok}.png")
                            if os.path.isfile(staged_file) and os.path.getsize(staged_file) > 0:
                                target_path = os.path.join(output_dir, f"{pkg_ok}_{device_key}_latest_icon.png")
                                shutil.move(staged_file, target_path)
                                results[pkg_ok] = target_path
                    finally:
                        shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass

        return results

    def extract_app_icon(
        self,
        device_id: str,
        package: str,
        output_dir: str,
        cache_token: Optional[str] = None,
        icon_res_ids: Optional[List[int]] = None,
        known_apk_path: Optional[str] = None,
    ) -> Optional[str]:
        """Extract the launcher icon declared in the installed APKs.

        Resolves android:icon / android:roundIcon from the binary manifest and
        resources.arsc (the same IDs PackageManager uses), including split APKs
        and adaptive-icon XML.         Returns a local PNG path, or None.
        """
        archive = None
        try:
            _validate_package(package)
            self.cleanup_icon_cache(output_dir, max_age_days=7)
            os.makedirs(output_dir, exist_ok=True)
            device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
            token = cache_token or ''
            token_key = hashlib.sha256(token.encode('utf-8')).hexdigest()[:10] if token else 'latest'
            local_icon_path = os.path.join(output_dir, f"{package}_{device_key}_{token_key}_icon.png")
            if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                return local_icon_path

            # Fast path: Use on-device PackageManager via app_process
            if self._ensure_icon_extractor(device_id):
                try:
                    cmd = [
                        'shell',
                        'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                        'app_process', '/',
                        'com.droidmgr.IconExtractor',
                        '--out=/data/local/tmp/droidmgr_icons',
                        package
                    ]
                    res = self._run_command(cmd, device_id, timeout=8)
                    if f"OK:{package}" in res:
                        self._run_command(['pull', f'/data/local/tmp/droidmgr_icons/{package}.png', local_icon_path], device_id, timeout=6)
                        if os.path.isfile(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                            return local_icon_path
                except Exception:
                    pass

            if known_apk_path and known_apk_path.endswith('.apk'):
                apk_paths = [known_apk_path]
            else:
                path_output = self._run_command(['shell', 'pm', 'path', package], device_id)
                apk_paths = []
                for line in path_output.splitlines():
                    line = line.strip()
                    if line.startswith('package:'):
                        p = line.replace('package:', '').strip()
                        if p.endswith('.apk'):
                            apk_paths.append(p)
            if not apk_paths:
                return None
            apk_paths.sort(key=lambda path: (0 if posixpath.basename(path) == 'base.apk' else 1, path))

            archive = _DeviceApkArchive(self, device_id, apk_paths)
            table = apk_icon.ResourceTable()
            for apk_path in apk_paths:
                arsc = archive.read(apk_path, 'resources.arsc')
                if arsc:
                    table.merge(apk_icon.parse_resource_table(arsc))

            res_ids: List[int] = []
            manifest = archive.read_name('AndroidManifest.xml')
            if manifest:
                icons = apk_icon.parse_manifest_icons(manifest)
                res_ids.extend(icons.candidate_ids())
            if icon_res_ids:
                for res_id in icon_res_ids:
                    if res_id not in res_ids:
                        res_ids.append(res_id)

            if self._render_icon_from_resources(archive, table, res_ids, local_icon_path):
                return local_icon_path
            if self._render_icon_from_filename_fallback(archive, local_icon_path):
                return local_icon_path
        except Exception:
            pass
        finally:
            if archive is not None:
                archive.close()
        return None



def _looks_like_unzip_error(data: bytes) -> bool:
    if not data:
        return True
    prefix = data[:48].lstrip().lower()
    return prefix.startswith(b'unzip:') or prefix.startswith(b'toybox') or prefix.startswith(b'/system/bin')

