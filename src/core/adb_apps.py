"""ADBManager mixin: installed apps, APK paths, install/uninstall."""

import hashlib
import json
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from . import apk_icon
from .adb_base import ADBCommandError
from .adb_parse_health import _display_app_name, _parse_diskstats
from .audit_logger import AuditLogger

# An app installed under one of these paths is part of the system image.
SYSTEM_APP_PATHS = ('/system', '/product', '/vendor', '/system_ext', '/odm', '/apex')


class _AppsMixin:
    """_AppsMixin for ADBManager (see adb_manager.py)."""

    def get_installed_apps(self, device_id: str) -> List[str]:
        output = self._run_command(['shell', 'pm', 'list', 'packages'], device_id)
        
        apps = []
        for line in output.split('\n'):
            if line.startswith('package:'):
                package = line.replace('package:', '').strip()
                apps.append(package)
        
        return sorted(apps)

    def _get_app_sizes(self, device_id: str, apps: List[Dict[str, Any]]) -> Dict[str, int]:
        """APK bytes per package, from one batched call to the disk stats service.

        Sizes are keyed by package name and cover system and user apps alike. A
        package the service does not list comes back as zero.
        """
        try:
            output = self._run_command(['shell', 'dumpsys', 'diskstats'], device_id)
        except Exception:
            return {}

        sizes = _parse_diskstats(output)
        return {app['package']: sizes.get(app['package'], 0) for app in apps}

    def get_installed_apps_details(self, device_id: str) -> List[Dict[str, Any]]:
        """Get installed apps with package, formatted name, path, type and APK size."""
        try:
            output = self._run_command(['shell', 'pm', 'list', 'packages', '-f'], device_id)
            apps = []

            for line in output.split('\n'):
                line = line.strip()
                if line.startswith('package:'):
                    line = line.replace('package:', '')
                    if '=' in line:
                        path, package = line.rsplit('=', 1)
                        is_system = path.startswith(SYSTEM_APP_PATHS)
                        apps.append({
                            'package': package,
                            'name': _display_app_name(package),
                            'path': path,
                            'is_system': is_system,
                            'type': 'System' if is_system else 'User'
                        })

            # Retrieve accurate, localized application labels via PackageManager API
            labels = {}
            device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
            cache_file = None
            try:
                from .config_manager import ConfigManager
                cache_dir = ConfigManager().get_cache_dir('labels')
                cache_file = os.path.join(cache_dir, f"labels_{device_key}.json")
                if os.path.isfile(cache_file):
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached = json.load(f)
                        if isinstance(cached, dict):
                            labels.update(cached)
            except Exception:
                pass

            all_pkgs = [a['package'] for a in apps]
            missing_pkgs = [p for p in all_pkgs if p not in labels]
            if missing_pkgs:
                query_pkgs = None if len(missing_pkgs) > len(all_pkgs) * 0.7 else missing_pkgs
                fetched = self.get_app_labels(device_id, query_pkgs)
                labels.update(fetched)
                if cache_file and fetched:
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(labels, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass

            for app in apps:
                pkg = app['package']
                if pkg in labels and labels[pkg]:
                    app['name'] = labels[pkg]

            sizes = self._get_app_sizes(device_id, apps)
            for app in apps:
                app['size_bytes'] = sizes.get(app['package'], 0)

            apps.sort(key=lambda x: x['name'].lower())
            return apps
        except Exception:
            pkgs = self.get_installed_apps(device_id)
            return [{'package': p, 'name': _display_app_name(p), 'path': '',
                     'is_system': False, 'type': 'Unknown', 'size_bytes': 0} for p in pkgs]

    def get_app_info(self, device_id: str, package: str) -> Dict[str, str]:
        _validate_package(package)
        output = self._run_command(['shell', 'dumpsys', 'package', package], device_id)

        info = {'package': package}
        icon_ids = apk_icon.parse_icon_resource_ids_from_dumpsys(output)

        for line in output.split('\n'):
            line = line.strip()
            if 'versionName=' in line:
                info['version_name'] = line.split('=', 1)[1]
            elif 'versionCode=' in line:
                # versionCode=123 minSdk=21 targetSdk=30
                info['version_code'] = line.split('=', 1)[1].split()[0]
            elif 'firstInstallTime=' in line:
                info['install_time'] = line.split('=', 1)[1]
            elif 'lastUpdateTime=' in line:
                info['update_time'] = line.split('=', 1)[1]
            elif 'codePath=' in line:
                info['path'] = line.split('=', 1)[1]
            elif 'installerPackageName=' in line:
                info['installer'] = line.split('=', 1)[1]
            elif 'userId=' in line:
                info['user_id'] = line.split('=', 1)[1]

        # Resolve exact APK file path via pm path
        try:
            pm_path_out = self._run_command(['shell', 'pm', 'path', package], device_id, timeout=8)
            for p_line in pm_path_out.splitlines():
                p_line = p_line.strip()
                if p_line.startswith('package:'):
                    info['path'] = p_line[8:].strip()
                    break
        except Exception:
            pass

        if icon_ids:
            info['icon_res_ids'] = icon_ids

        # Resolve display name
        device_key = hashlib.sha256(device_id.encode('utf-8')).hexdigest()[:10]
        try:
            from .config_manager import ConfigManager
            cache_file = os.path.join(ConfigManager().get_cache_dir('labels'), f"labels_{device_key}.json")
            if os.path.isfile(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    labels = json.load(f)
                    if package in labels and labels[package]:
                        info['name'] = labels[package]
        except Exception:
            pass

        if 'name' not in info:
            lbl = self.get_app_labels(device_id, [package]).get(package)
            info['name'] = lbl if lbl else _display_app_name(package)

        return info

    def install_apk(self, device_id: str, apk_path: str,
                    options: Optional[Dict[str, bool]] = None) -> None:
        path = Path(apk_path)
        if not path.exists():
            raise FileNotFoundError(f"APK file does not exist: {apk_path}")
        if not path.is_file():
            raise ValueError(f"Specified path is not a file: {apk_path}")
        if path.suffix.lower() != '.apk':
            raise ValueError(f"File does not have a .apk extension: {apk_path}")
        if not os.access(path, os.R_OK):
            raise PermissionError(f"APK file is not readable: {apk_path}")

        AuditLogger.log(device_id, "INSTALL_APK", str(path))
        args = ['install'] + _install_flags(options) + [str(path)]
        output = self._run_command(args, device_id)
        _raise_install_failure(output)

    def install_apk_set(self, device_id: str, apk_paths: List[str],
                        options: Optional[Dict[str, bool]] = None) -> None:
        """Install one app made of a base APK plus its splits, one command.

        Split packages cannot go install-by-install: the device rejects a
        base APK whose splits are missing. This hands every member of the
        same app to a single `adb install-multiple`, base APK first.
        """
        paths = [Path(p) for p in apk_paths]
        if not paths:
            raise ValueError("No APK paths were given.")
        for path in paths:
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"APK file does not exist: {path}")
            if not os.access(path, os.R_OK):
                raise PermissionError(f"APK file is not readable: {path}")

        names = ', '.join(path.name for path in paths)
        AuditLogger.log(device_id, "INSTALL_APK", f"set of {len(paths)}: {names}")
        args = ['install-multiple'] + _install_flags(options) + [str(path) for path in paths]
        output = self._run_command(args, device_id)
        _raise_install_failure(output)

    def get_apk_paths(self, device_id: str, package: str) -> List[Dict[str, str]]:
        """List the APK files behind an installed package using `pm path`.

        Returns one entry per file, in `pm path` order: the base APK comes
        first, then any splits. Each entry is
        {'split': '' for base.apk or the split name without its extension,
         'name': the on-device file name, 'path': the on-device path}.
        """
        _validate_package(package)
        output = self._run_command(['shell', 'pm', 'path', package], device_id)

        entries: List[Dict[str, str]] = []
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith('package:'):
                continue
            remote_path = line.split(':', 1)[1].strip()
            if not remote_path:
                continue
            name = posixpath.basename(remote_path)
            stem = name[:-4] if name.lower().endswith('.apk') else name
            entries.append({
                'split': '' if stem == 'base' else stem,
                'name': name,
                'path': remote_path,
            })

        if not entries:
            raise ADBCommandError(
                f"'pm path {package}' reported no APK files. "
                "The app may be disabled, or not installed for the current user."
            )
        return entries

    def extract_apk(self, device_id: str, package: str, destination: str,
                    version: str = '') -> Dict[str, Any]:
        """Pull every APK behind an installed package into a local folder.

        A package with only a base APK is written as <package>_<version>.apk.
        A split package is bundled into <package>_<version>.apks, a zip holding
        base.apk plus each split_<name>.apk, which is what split-installers
        such as SAI expect. Returns {'path', 'members', 'is_split'}.
        """
        _validate_package(package)
        AuditLogger.log(device_id, "EXTRACT_APK", f"{package} -> {destination}")

        if not version:
            try:
                version = self.get_app_info(device_id, package).get('version_name', '') or ''
            except Exception:
                version = ''
        version = version.strip()
        # Version names such as "1.2.3 beta" are legal in a filename, but the
        # space makes the result awkward to type, so collapse whitespace runs.
        version = re.sub(r'\s+', '_', version)
        stem = f"{package}_{self._safe_ntfs_component(version)}" if version else package

        entries = self.get_apk_paths(device_id, package)
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)

        if len(entries) == 1 and not entries[0]['split']:
            local_path = target / f"{stem}.apk"
            self.download_file(device_id, entries[0]['path'], str(local_path))
            return {'path': str(local_path), 'members': [entries[0]['name']], 'is_split': False}

        archive = target / f"{stem}.apks"
        members: List[str] = []
        # Pull into a scratch folder so the chosen destination only ever gains
        # the finished file, never the loose base.apk / split_*.apk.
        with tempfile.TemporaryDirectory(prefix='droidmgr-apk-') as scratch_dir:
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as bundle:
                for entry in entries:
                    scratch = Path(scratch_dir) / entry['name']
                    self.download_file(device_id, entry['path'], str(scratch))
                    bundle.write(scratch, arcname=entry['name'])
                    members.append(entry['name'])
        return {'path': str(archive), 'members': members, 'is_split': True}

    def uninstall_app(self, device_id: str, package: str,
                      keep_data: bool = False, all_users: bool = False) -> None:
        """Uninstall an application, optionally keeping its data as well.

        Args:
            keep_data: `pm uninstall -k` - the app leaves the launcher and its
                data plus cache stay on the device
            all_users: `--user all` - remove the app for every device user,
                not just the one adb talks to
        """
        _validate_package(package)
        args = ['shell', 'pm', 'uninstall']
        if keep_data:
            args.append('-k')
        if all_users:
            args.extend(['--user', 'all'])
        args.append(package)
        AuditLogger.log(device_id, "UNINSTALL_APP", package)
        self._run_command(args, device_id)

    def get_runtime_permissions(self, device_id: str, package: str) -> Dict[str, bool]:
        """Runtime permissions reported by `dumpsys package`, name -> granted.

        The same permission can appear once per device user block; a later
        line replaces the earlier one, which keeps the last user's state.
        """
        _validate_package(package)
        output = self._run_command(['shell', 'dumpsys', 'package', package], device_id)
        perms: Dict[str, bool] = {}
        pattern = re.compile(r'^([a-zA-Z][\w.]*): granted=(true|false)$')
        for line in output.splitlines():
            match = pattern.match(line.strip())
            if match:
                perms[match.group(1)] = match.group(2) == 'true'
        return perms

    def grant_permission(self, device_id: str, package: str, permission: str) -> None:
        """Give one runtime permission to an app (`pm grant`)."""
        _validate_package(package)
        AuditLogger.log(device_id, "GRANT_PERMISSION", f"{package}: {permission}")
        self._run_command(['shell', 'pm', 'grant', package, permission], device_id)

    def revoke_permission(self, device_id: str, package: str, permission: str) -> None:
        """Take one runtime permission away from an app (`pm revoke`)."""
        _validate_package(package)
        AuditLogger.log(device_id, "REVOKE_PERMISSION", f"{package}: {permission}")
        self._run_command(['shell', 'pm', 'revoke', package, permission], device_id)

    def grant_all_runtime_permissions(self, device_id: str, package: str) -> Dict[str, Any]:
        """Try to grant every runtime permission the app requests, via root.

        The shell user can only change runtime grants of an app it installed
        itself; for the usual case this needs `su`, so failures carry the
        device's own message.

        Returns:
            {'granted': [names], 'failed': {name: reason}, 'requested': [names]}
        """
        _validate_package(package)
        output = self._run_command(['shell', 'dumpsys', 'package', package], device_id)

        requested: List[str] = []
        in_block = False
        for line in output.splitlines():
            text = line.strip()
            if text.startswith('requested permissions:'):
                in_block = True
                continue
            if in_block:
                if not text or text.endswith('permissions:'):
                    in_block = False
                    continue
                requested.append(text)

        granted: List[str] = []
        failed: Dict[str, str] = {}
        for name in requested:
            try:
                self._run_command(['shell', 'su', '-c', f'pm grant {package} {name}'],
                                  device_id)
                granted.append(name)
            except Exception as exc:
                failed[name] = str(exc)
        return {'granted': granted, 'failed': failed, 'requested': requested}

    def start_app(self, device_id: str, package: str) -> None:
        _validate_package(package)
        AuditLogger.log(device_id, "START_APP", package)
        self._run_command(
            ['shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'],
            device_id
        )

    def stop_app(self, device_id: str, package: str) -> None:
        _validate_package(package)
        AuditLogger.log(device_id, "STOP_APP", package)
        self._run_command(['shell', 'am', 'force-stop', package], device_id)

    def clear_app_data(self, device_id: str, package: str) -> None:
        """Delete an application's stored data, which takes its cache with it.

        Android offers no way to clear one app's cache on its own: the cache
        directory belongs to the app's uid, and the only shell-reachable route
        to it is 'pm clear', which empties the whole data directory. Some ROMs
        withhold CLEAR_APP_USER_DATA from the shell user, and this raises.
        """
        _validate_package(package)
        AuditLogger.log(device_id, "CLEAR_APP_DATA", package)
        self._run_command(['shell', 'pm', 'clear', package], device_id)

    def get_app_labels(self, device_id: str, packages: Optional[List[str]] = None) -> Dict[str, str]:
        """Query official, localized application labels via on-device PackageManager."""
        labels: Dict[str, str] = {}
        if not device_id or not self._ensure_icon_extractor(device_id):
            return labels

        try:
            cmd = [
                'shell',
                'CLASSPATH=/data/local/tmp/droidmgr_icon.jar',
                'app_process', '/',
                'com.droidmgr.IconExtractor',
                '--labels'
            ]
            if packages:
                chunk_size = 50
                for i in range(0, len(packages), chunk_size):
                    chunk = packages[i:i + chunk_size]
                    out = self._run_command([*cmd, *chunk], device_id, timeout=15)
                    for line in out.splitlines():
                        if line.startswith('LABEL:'):
                            parts = line[6:].split('\t', 1)
                            if len(parts) == 2 and parts[1].strip():
                                labels[parts[0].strip()] = parts[1].strip()
            else:
                out = self._run_command(cmd, device_id, timeout=25)
                for line in out.splitlines():
                    if line.startswith('LABEL:'):
                        parts = line[6:].split('\t', 1)
                        if len(parts) == 2 and parts[1].strip():
                            labels[parts[0].strip()] = parts[1].strip()
        except Exception:
            pass

        return labels



_PACKAGE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$')

def _validate_package(package: str) -> None:
    if not package or not _PACKAGE_RE.match(package):
        raise ValueError(f"Invalid package name: {package!r}")


def _install_flags(options: Optional[Dict[str, bool]]) -> List[str]:
    """The pm switches an install options dict describes; -r stays default."""
    options = options or {}
    flags = []
    if options.get('replace', True):
        flags.append('-r')
    if options.get('allow_downgrade'):
        flags.append('-d')
    if options.get('test_only'):
        flags.append('-t')
    return flags


def _raise_install_failure(output: str) -> None:
    """Turn a pm-install output containing Failure into the friendly error."""
    if "Failure" in output or "Success" not in output:
        error_reason = output
        match = re.search(r'Failure\s*\[(.*?)\]', output)
        if match:
            code = match.group(1)
            friendly_messages = {
                'INSTALL_FAILED_ALREADY_EXISTS': 'Application with the same package name already exists.',
                'INSTALL_FAILED_INVALID_APK': 'The APK file is invalid or corrupted.',
                'INSTALL_FAILED_INSUFFICIENT_STORAGE': 'Device has insufficient storage space.',
                'INSTALL_FAILED_DUPLICATE_PACKAGE': 'Duplicate package name found on device.',
                'INSTALL_FAILED_NO_SHARED_USER': 'Shared user does not exist.',
                'INSTALL_FAILED_UPDATE_INCOMPATIBLE': 'Update is incompatible with currently installed version.',
                'INSTALL_FAILED_SHARED_USER_INCOMPATIBLE': 'Shared user signature mismatch.',
                'INSTALL_FAILED_MISSING_SHARED_LIBRARY': 'Required shared library is missing on device.',
                'INSTALL_FAILED_REPLACE_COULDNT_DELETE': 'Failed to replace existing installation.',
                'INSTALL_FAILED_DEXOPT': 'DEX optimization failed.',
                'INSTALL_FAILED_OLDER_SDK': 'APK requires a newer Android version (minSdk higher than device SDK).',
                'INSTALL_FAILED_CONFLICTING_PROVIDER': 'Conflicting content provider exists on device.',
                'INSTALL_FAILED_NEWER_SDK': 'APK requires an older Android version.',
                'INSTALL_FAILED_TEST_ONLY': 'APK is marked test-only.',
                'INSTALL_FAILED_CPU_ABI_INCOMPATIBLE': 'Native CPU architecture (ABI) is incompatible with device.',
                'INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES': 'Package certificates mismatch.',
                'INSTALL_FAILED_VERSION_DOWNGRADE': 'Cannot downgrade application to an older version code.'
            }
            explanation = friendly_messages.get(code, code)
            error_reason = f"{code}: {explanation}"
        raise RuntimeError(f"Installation failed: {error_reason}")
