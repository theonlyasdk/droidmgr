"""Manages ADB operations for Android devices."""

import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
import re
from .audit_logger import AuditLogger





class ADBError(RuntimeError):
    """Base exception for ADB operations."""
    pass

class ADBNotFoundError(ADBError):
    """Raised when the ADB executable is not found on PATH or specified location."""
    pass

class ADBDeviceNotFoundError(ADBError):
    """Raised when a specified device is not found or disconnected."""
    pass


class ADBDeviceOfflineError(ADBError):
    """Raised when the target device is offline or unauthorized."""
    pass

class ADBCommandError(ADBError):
    """Raised when an ADB command fails execution."""
    pass

_PACKAGE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$')

def _validate_package(package: str) -> None:
    if not package or not _PACKAGE_RE.match(package):
        raise ValueError(f"Invalid package name: {package!r}")


class ADBManager:

    
    def __init__(self, adb_path: Path):
        self.adb_path = str(adb_path)
    
    @staticmethod
    def _sanitize_adb_error(err_text: str, device_id: Optional[str] = None) -> str:
        if not err_text:
            return ""
        # Strip ANSI escape sequences
        text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', err_text)
        # Redact device serial if present
        if device_id and device_id in text:
            text = text.replace(device_id, '[REDACTED_SERIAL]')
        text = text.strip()
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    def _run_command(self, args: List[str], device_id: Optional[str] = None) -> str:
        cmd = [self.adb_path]
        
        if device_id:
            cmd.extend(['-s', device_id])
        
        cmd.extend(args)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except FileNotFoundError:
            raise ADBNotFoundError(f"ADB executable not found at '{self.adb_path}'. Please verify the path in Preferences > External Tools.")
        except subprocess.CalledProcessError as e:

            stderr = e.stderr.strip() if e.stderr else (e.stdout.strip() if e.stdout else str(e))
            clean_err = self._sanitize_adb_error(stderr, device_id)
            
            lower_err = stderr.lower()
            if 'device not found' in lower_err or 'no devices/emulators found' in lower_err:
                raise ADBDeviceNotFoundError(f"Device not found or disconnected: {clean_err}")
            elif 'device offline' in lower_err or 'device unauthorized' in lower_err:
                raise ADBDeviceOfflineError(f"Device is offline or unauthorized: {clean_err}")
            else:
                raise ADBCommandError(f"ADB command failed: {clean_err}")

    
    def get_devices(self) -> List[Dict[str, str]]:
        output = self._run_command(['devices', '-l'])
        devices = []
        
        for line in output.split('\n')[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 2:
                device_id = parts[0]
                status = parts[1]
                
                info = {'id': device_id, 'status': status}
                
                for part in parts[2:]:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        info[key] = value
                
                devices.append(info)
        
        return devices
    
    def get_device_model(self, device_id: str) -> str:
        try:
            return self._run_command(['shell', 'getprop', 'ro.product.model'], device_id)
        except RuntimeError:
            return "Unknown"

    def get_detailed_device_info(self, device_id: str) -> Dict[str, str]:
        """Fetch detailed non-confidential device information including CPU and RAM."""
        info = {}
        try:
            # Basic props
            info['model'] = self.get_device_model(device_id)
            info['manufacturer'] = self._run_command(['shell', 'getprop', 'ro.product.manufacturer'], device_id)
            info['android_version'] = self._run_command(['shell', 'getprop', 'ro.build.version.release'], device_id)
            info['android_codename'] = self._run_command(['shell', 'getprop', 'ro.build.version.codename'], device_id)
            info['build_id'] = self._run_command(['shell', 'getprop', 'ro.build.display.id'], device_id)
            info['kernel'] = self._run_command(['shell', 'uname', '-rs'], device_id)
            info['product_name'] = self._run_command(['shell', 'getprop', 'ro.product.name'], device_id)
            info['serial'] = device_id

            # CPU Info
            # Try ro.soc.model first (Android 12+)
            soc = self._run_command(['shell', 'getprop', 'ro.soc.model'], device_id).strip()
            if not soc:
                soc = self._run_command(['shell', 'getprop', 'ro.board.platform'], device_id).strip()
            
            # Extract from /proc/cpuinfo for more detail if needed
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            hardware = ""
            for line in cpuinfo.split('\n'):
                if line.startswith('Hardware'):
                    hardware = line.split(':', 1)[1].strip()
                    break
            
            info['cpu'] = soc if soc else (hardware if hardware else "Unknown")
            if hardware and soc and hardware.lower() != soc.lower():
                info['cpu'] = f"{soc} ({hardware})"

            # Memory Info
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
            
            if total_kb:
                total_gb = total_kb / (1024 * 1024)
                avail_gb = avail_kb / (1024 * 1024)
                info['ram'] = f"{avail_gb:.1f} GB / {total_gb:.1f} GB free"
            else:
                info['ram'] = "Unknown"

        except Exception as e:
            info['error'] = str(e)
        return info

    def trigger_easter_egg(self, device_id: str) -> None:
        """Attempt to launch the Android Easter Egg activity."""
        # Common locations for Easter Egg
        activities = [
            "com.android.egg/.EasterEggActivity",
            "com.android.systemui/.DessertCase",
            "com.android.systemui/.BeanBag",
            "com.android.egg/com.android.egg.land.EasterEggActivity"
        ]
        
        for activity in activities:
            try:
                self._run_command(['shell', 'am', 'start', '-n', activity], device_id)
                return # Stop if one succeeds
            except:
                continue
        
        # Fallback to general intent
        try:
            self._run_command(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-n', 'com.android.egg/.EasterEggActivity'], device_id)
        except:
            pass
    
    def get_running_processes(self, device_id: str) -> List[Dict[str, Any]]:
        try:
            output = self._run_command(['shell', 'top', '-n', '1', '-b'], device_id)
            return self._parse_top_output(output)
        except:
            try:
                output = self._run_command(['shell', 'ps', '-eo', 'pid,user,pcpu,vsz,args'], device_id)
                return self._parse_ps_extended(output)
            except:
                output = self._run_command(['shell', 'ps', '-A'], device_id)
                return self._parse_basic_processes(output)
    
    def _parse_top_output(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        header_found = False
        header_line = None
        
        for i, line in enumerate(lines):
            if 'PID' in line.upper():
                header_found = True
                header_line = line
                continue
            
            if header_found and line.strip():
                parts = line.split()
                if len(parts) < 5:
                    continue
                
                try:
                    pid_idx = 0
                    user_idx = 1
                    cpu_idx = None
                    mem_idx = None
                    
                    for idx, part in enumerate(parts):
                        if '%' in part:
                            if cpu_idx is None:
                                cpu_idx = idx
                            elif mem_idx is None and idx != cpu_idx:
                                mem_idx = idx
                    
                    pid = parts[pid_idx] if parts[pid_idx].isdigit() else '0'
                    user = parts[user_idx] if len(parts) > user_idx else 'unknown'
                    cpu = parts[cpu_idx].replace('%', '') if cpu_idx and len(parts) > cpu_idx else '0'
                    
                    mem_val = '0'
                    if mem_idx and len(parts) > mem_idx:
                        mem_part = parts[mem_idx].replace('%', '')
                        try:
                            mem_pct = float(mem_part)
                            mem_val = f"{mem_pct:.1f}%"
                        except:
                            mem_val = mem_part
                    else:
                        # Improved heuristic: look for columns with memory suffixes
                        # Standard top: VIRT is column 4, RES is column 5.
                        # We prefer the second one found (RES) as it's closer to physical usage.
                        mem_candidates = []
                        for idx in range(len(parts)):
                            if any(suffix in parts[idx] for suffix in ['K', 'M', 'G']) and any(c.isdigit() for c in parts[idx]):
                                mem_candidates.append(parts[idx])
                        
                        if len(mem_candidates) >= 2:
                            mem_val = mem_candidates[1] # Use RES
                        elif mem_candidates:
                            mem_val = mem_candidates[0] # Fallback to VIRT
                    
                    # Locate ARGS column (typically starts after TIME+ which contains ':')
                    time_idx = -1
                    for idx, part in enumerate(parts):
                        if ':' in part and idx >= 5:
                            time_idx = idx
                            break
                            
                    if time_idx != -1 and len(parts) > time_idx + 1:
                        name = parts[time_idx + 1]
                    elif len(parts) > 11:
                        name = parts[11]
                    else:
                        name = parts[-1] if parts else 'unknown'
                    
                    if not pid.isdigit() or pid == '0':
                        continue
                    
                    process = {
                        'pid': pid,
                        'user': user if len(user) > 1 else 'sys',
                        'cpu': cpu,
                        'mem': self._format_memory(mem_val),
                        'name': name
                    }
                    processes.append(process)
                except:
                    continue
        
        if processes:
            return sorted(processes, key=lambda x: float(x.get('cpu', 0) or 0), reverse=True)[:50]
        
        return self._parse_basic_processes(output)
    
    def _parse_ps_extended(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split(None, 4)
            if len(parts) >= 5:
                cmd_parts = parts[4].split()
                name = cmd_parts[0] if cmd_parts else 'unknown'
                process = {
                    'pid': parts[0],
                    'user': parts[1],
                    'cpu': parts[2],
                    'mem': self._format_memory(parts[3]),
                    'name': name
                }
                processes.append(process)

        
        return processes[:50]
    
    def _parse_basic_processes(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 9:
                process = {
                    'pid': parts[1],
                    'user': parts[0],
                    'cpu': '0',
                    'mem': '0',
                    'name': parts[-1]
                }
                processes.append(process)
        
        return processes[:50]
    
    def _format_memory(self, mem_str: str) -> str:
        if not mem_str or mem_str == '0':
            return '0 KB'
        
        mem_str = mem_str.strip()
        
        if '%' in mem_str:
            return mem_str
        
        # Handle cases where it already has a suffix
        if 'G' in mem_str or 'M' in mem_str or 'K' in mem_str:
            return mem_str.replace('G', ' GB').replace('M', ' MB').replace('K', ' KB')
        
        try:
            mem_kb = int(mem_str)
            if mem_kb < 1024:
                return f"{mem_kb} KB"
            elif mem_kb < 1024 * 1024:
                return f"{mem_kb // 1024} MB"
            else:
                return f"{mem_kb / (1024 * 1024):.1f} GB"
        except ValueError:
            return mem_str

    def _format_file_size(self, size_str: str) -> str:
        try:
            size_bytes = int(size_str)
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
        except ValueError:
            return size_str
    
    def get_system_stats(self, device_id: str) -> Dict[str, Any]:
        stats = {}
        
        try:
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            free_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    free_kb = int(line.split()[1])
                    
            target_avail = avail_kb if avail_kb > 0 else free_kb
            if target_avail > 0:
                stats['free_memory'] = self._format_memory(str(target_avail))
            if total_kb > 0:
                stats['total_memory'] = self._format_memory(str(total_kb))

        except:
            pass
        
        try:
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            cpu_count = cpuinfo.count('processor')
            stats['cpu_cores'] = cpu_count if cpu_count > 0 else 1
        except:
            stats['cpu_cores'] = 1
        
        return stats
    
    def kill_process(self, device_id: str, pid: str) -> None:
        AuditLogger.log(device_id, "KILL_PROCESS", f"PID: {pid}")
        self._run_command(['shell', 'kill', pid], device_id)

    
    def get_installed_apps(self, device_id: str) -> List[str]:
        output = self._run_command(['shell', 'pm', 'list', 'packages'], device_id)
        
        apps = []
        for line in output.split('\n'):
            if line.startswith('package:'):
                package = line.replace('package:', '').strip()
                apps.append(package)
        
        return sorted(apps)

    def get_installed_apps_details(self, device_id: str) -> List[Dict[str, Any]]:
        """Get list of installed apps with package, formatted name, path, and category size."""
        try:
            output = self._run_command(['shell', 'pm', 'list', 'packages', '-f'], device_id)
            apps = []
            
            known_names = {
                'com.android.settings': 'Settings',
                'com.android.systemui': 'System UI',
                'com.google.android.youtube': 'YouTube',
                'org.telegram.messenger': 'Telegram',
                'notion.id': 'Notion',
                'app.zophop': 'Chalo',
                'com.android.chrome': 'Chrome',
                'com.google.android.apps.maps': 'Google Maps',
                'com.google.android.keep': 'Google Keep',
                'com.whatsapp': 'WhatsApp',
                'com.instagram.android': 'Instagram',
                'com.facebook.katana': 'Facebook',
                'com.twitter.android': 'X (Twitter)',
                'com.spotify.music': 'Spotify',
                'com.netflix.mediaclient': 'Netflix',
                'com.google.android.gms': 'Google Play Services',
                'com.android.vending': 'Google Play Store',
                'com.google.android.calculator': 'Calculator',
                'com.google.android.calendar': 'Calendar',
                'com.google.android.contacts': 'Contacts',
                'com.google.android.deskclock': 'Clock',
                'com.google.android.dialer': 'Phone',
                'com.google.android.apps.photos': 'Google Photos',
            }

            for line in output.split('\n'):
                line = line.strip()
                if line.startswith('package:'):
                    line = line.replace('package:', '')
                    if '=' in line:
                        path, package = line.rsplit('=', 1)
                        if package in known_names:
                            name = known_names[package]
                        else:
                            parts = package.split('.')
                            raw_name = parts[-1] if len(parts[-1]) > 2 else (parts[-2] if len(parts) > 1 else package)
                            name = raw_name.replace('_', ' ').replace('-', ' ').title()
                            
                        size_str = 'System App' if path.startswith(('/system', '/product', '/vendor', '/system_ext')) else 'User App'
                        apps.append({
                            'package': package,
                            'name': name,
                            'path': path,
                            'size': size_str
                        })
            
            apps.sort(key=lambda x: x['name'].lower())
            return apps
        except Exception:
            pkgs = self.get_installed_apps(device_id)
            return [{'package': p, 'name': p.split('.')[-1].title(), 'path': '', 'size': 'N/A'} for p in pkgs]

    
    def get_app_info(self, device_id: str, package: str) -> Dict[str, str]:
        _validate_package(package)
        output = self._run_command(['shell', 'dumpsys', 'package', package], device_id)

        info = {'package': package}
        
        for line in output.split('\n'):
            line = line.strip()
            if 'versionName=' in line:
                info['version_name'] = line.split('=')[1]
            elif 'versionCode=' in line:
                # versionCode=123 minSdk=21 targetSdk=30
                info['version_code'] = line.split('=')[1].split()[0]
            elif 'firstInstallTime=' in line:
                info['install_time'] = line.split('=')[1]
            elif 'lastUpdateTime=' in line:
                info['update_time'] = line.split('=')[1]
            elif 'codePath=' in line:
                info['path'] = line.split('=')[1]
            elif 'installerPackageName=' in line:
                info['installer'] = line.split('=')[1]
            elif 'userId=' in line:
                info['user_id'] = line.split('=')[1]
                
        return info


    def install_apk(self, device_id: str, apk_path: str) -> None:
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
        output = self._run_command(['install', '-r', str(path)], device_id)
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



    def uninstall_app(self, device_id: str, package: str) -> None:
        """Uninstall an application from the device."""
        _validate_package(package)
        AuditLogger.log(device_id, "UNINSTALL_APP", package)
        self._run_command(['uninstall', package], device_id)

    
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

    
    def list_files(self, device_id: str, path: str = '/sdcard/', show_hidden: bool = True, use_exact_sizes: bool = False) -> List[Dict[str, Any]]:
        if not path.strip():
            path = "/"
        if not path.endswith('/'):
            path += '/'
            
        try:
            output = self._run_command(['shell', 'ls', '-la', f'"{path}"'], device_id)
        except RuntimeError as e:
            # Handle empty directories or access errors gracefully
            if "No such file or directory" in str(e):
                return []
            raise e
        
        lines = output.split('\n')
        files = []
        
        # Step 1: Detect metadata column count from '.' or '..' entries
        # This is the most robust way as metadata columns are fixed in a single 'ls' output
        metadata_cols = -1
        for line in lines:
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            parts = line.split()
            # '.' and '..' are always single-part names at the end of the metadata
            if len(parts) >= 4 and parts[-1] in ('.', '..'):
                metadata_cols = len(parts) - 1
                break
                
        # Fallback if no '.' or '..' found (unlikely with -la)
        if metadata_cols == -1:
            metadata_cols = 7 # Standard toybox/toolbox default
            
        for line in lines:
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            
            # Handle symlinks: split line to isolate name from target path
            if ' -> ' in line:
                line_parts = line.split(' -> ', 1)
                line = line_parts[0]
                
            parts = line.split()
            if not parts:
                continue
                
            # Skip inaccessible entries where permissions could not be read (e.g. l????????? or d?????????)
            if '?' in parts[0]:
                continue
                
            if len(parts) <= metadata_cols:
                continue
                
            permissions = parts[0]
            is_dir = permissions.startswith('d')
            is_symlink = permissions.startswith('l')
            if is_symlink:
                is_dir = True # Treat symlinks as something you can double click
                
            # Name is everything after the metadata columns
            name = ' '.join(parts[metadata_cols:])

            
            # Skip navigation entries in the final list
            if name in ('.', '..'):
                continue
            
            # Filter hidden files if requested
            if not show_hidden and name.startswith('.') and name != '..':
                continue
            
            # Metadata columns parsing
            user = parts[2] if len(parts) > 2 else "unknown"
            group = parts[3] if len(parts) > 3 else "unknown"
            
            # Date and Time are the last columns before name
            date_str = parts[metadata_cols-2] if metadata_cols >= 2 else ""
            time_str = parts[metadata_cols-1] if metadata_cols >= 1 else ""
            date_time = f"{date_str} {time_str}".strip()
            
            # Size candidate search
            size = '0'
            size_candidates = parts[max(0, metadata_cols-5):metadata_cols-1]
            for cand in reversed(size_candidates):
                if cand.isdigit():
                    size = cand
                    break
            
            display_size = f"{size} B" if use_exact_sizes else self._format_file_size(size)
                    
            file_info = {
                'permissions': permissions,
                'user': user,
                'group': group,
                'date_time': date_time,
                'size_raw': size,
                'size': display_size,
                'name': name,
                'is_dir': is_dir,
                'full_path': path + name
            }
            files.append(file_info)
            
        return sorted(files, key=lambda x: (not x.get('is_dir', False), (x.get('name') or '').lower()))
    
    def download_file(self, device_id: str, remote_path: str, local_path: str) -> None:
        self._run_command(['pull', remote_path, local_path], device_id)
    
    def upload_file(self, device_id: str, local_path: str, remote_path: str) -> None:
        self._run_command(['push', local_path, remote_path], device_id)
    
    PROTECTED_PATHS = {
        '/', '/system', '/system/app', '/system/priv-app', '/system/bin', '/system/etc',
        '/data', '/proc', '/dev', '/sbin', '/vendor', '/product', '/system_ext',
        '/odm', '/apex', '/sys', '/etc', '/bin', '/mnt', '/root'
    }

    def delete_file(self, device_id: str, remote_path: str) -> None:
        clean_path = remote_path.strip()
        if not clean_path or clean_path == '/':
            raise PermissionError("Deletion of root directory '/' is strictly prohibited.")
            
        norm_path = clean_path.rstrip('/')
        if not norm_path:
            norm_path = '/'

        if norm_path in self.PROTECTED_PATHS:
            raise PermissionError(f"Deletion of protected system path '{remote_path}' is strictly prohibited.")

        for protected in self.PROTECTED_PATHS:
            if protected != '/' and (protected == norm_path or protected.startswith(norm_path + '/')):
                raise PermissionError(f"Deletion of '{remote_path}' is prohibited because it is a parent of protected system path '{protected}'.")

        AuditLogger.log(device_id, "DELETE_FILE", remote_path)
        self._run_command(['shell', 'rm', '-rf', f'"{remote_path}"'], device_id)


    def rename_file(self, device_id: str, old_path: str, new_path: str) -> None:
        AuditLogger.log(device_id, "RENAME_FILE", f"From '{old_path}' to '{new_path}'")
        self._run_command(['shell', 'mv', f'"{old_path}"', f'"{new_path}"'], device_id)

    def move_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        AuditLogger.log(device_id, "MOVE_FILE", f"From '{src_path}' to '{dest_path}'")
        self._run_command(['shell', 'mv', f'"{src_path}"', f'"{dest_path}"'], device_id)

    def copy_file(self, device_id: str, src_path: str, dest_path: str) -> None:
        AuditLogger.log(device_id, "COPY_FILE", f"From '{src_path}' to '{dest_path}'")
        self._run_command(['shell', 'cp', '-r', f'"{src_path}"', f'"{dest_path}"'], device_id)

    def make_directory(self, device_id: str, path: str) -> None:
        """Create a directory on the device."""
        AuditLogger.log(device_id, "MAKE_DIR", path)
        self._run_command(['shell', 'mkdir', '-p', f'"{path}"'], device_id)



    def get_storage_info(self, device_id: str) -> Dict[str, str]:
        """Fetch storage space and partition information."""
        info = {}
        try:
            output = self._run_command(['shell', 'df', '-h'], device_id)
        except Exception:
            try:
                output = self._run_command(['shell', 'df'], device_id)
            except Exception as e:
                return {'summary': 'Storage info unavailable', 'raw': str(e)}
        
        info['raw'] = output
        mount_summaries = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith('Filesystem') or line.startswith('Sys. filesystem'):
                continue
            parts = line.split()
            if len(parts) >= 5:
                mounted_on = parts[-1]
                if any(m in mounted_on for m in ['/data', '/sdcard', '/storage', '/system', '/vendor', '/product']) or mounted_on == '/':
                    size = parts[1] if len(parts) >= 2 else '?'
                    used = parts[2] if len(parts) >= 3 else '?'
                    free = parts[3] if len(parts) >= 4 else '?'
                    use_pct = parts[4] if len(parts) >= 5 else '?'
                    mount_summaries.append(f"{mounted_on} ({free} free of {size}, {use_pct} used)")
        
        if mount_summaries:
            info['summary'] = ", ".join(mount_summaries)
        else:
            clean_lines = [l.strip() for l in output.splitlines() if l.strip() and not l.startswith('Filesystem')]
            info['summary'] = " | ".join(clean_lines[:5])
        return info

    def get_battery_info(self, device_id: str) -> str:
        """Fetch battery level and charging status."""
        try:
            output = self._run_command(['shell', 'dumpsys', 'battery'], device_id)
            level = ""
            status = ""
            for line in output.splitlines():
                line = line.strip()
                if line.startswith('level:'):
                    level = line.split(':', 1)[1].strip() + "%"
                elif line.startswith('status:'):
                    st_val = line.split(':', 1)[1].strip()
                    st_map = {'1': 'Unknown', '2': 'Charging', '3': 'Discharging', '4': 'Not charging', '5': 'Full'}
                    status = st_map.get(st_val, f"Code {st_val}")
            if level:
                return f"Level: {level}" + (f", Status: {status}" if status else "")
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_display_info(self, device_id: str) -> str:
        """Fetch screen resolution and density."""
        try:
            size_out = self._run_command(['shell', 'wm', 'size'], device_id).strip()
            density_out = self._run_command(['shell', 'wm', 'density'], device_id).strip()
            size = size_out.replace('Physical size:', '').strip()
            density = density_out.replace('Physical density:', '').strip()
            return f"Resolution: {size}, Density: {density}"
        except Exception:
            return "Unknown"

    def generate_llm_report(self, device_id: str, progress_callback=None) -> str:
        """Generate a single information-dense report paragraph for LLM analysis."""
        def update_p(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        update_p(10, "Gathering device specs and system properties...")
        info = self.get_detailed_device_info(device_id)

        update_p(30, "Checking storage space and system health...")
        storage_info = self.get_storage_info(device_id)
        battery_info = self.get_battery_info(device_id)
        display_info = self.get_display_info(device_id)

        update_p(55, "Fetching active process list...")
        try:
            processes = self.get_running_processes(device_id)
        except Exception:
            processes = []

        update_p(75, "Retrieving installed applications...")
        try:
            apps = self.get_installed_apps(device_id)
        except Exception:
            apps = []

        update_p(90, "Formulating single information-dense paragraph report...")
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def clean(val):
            return str(val).replace('\n', ' ').replace('\r', '').strip()

        proc_str_list = [
            f"{p['name']} (PID: {p['pid']}, User: {p['user']}, CPU: {p['cpu']}%, Mem: {p['mem']})"
            for p in processes
        ]
        proc_formatted = ", ".join(proc_str_list) if proc_str_list else "None detected"

        apps_formatted = ", ".join(apps) if apps else "None detected"

        report_paragraph = (
            f"DEVICE LLM SUMMARY REPORT [{timestamp}] | "
            f"Device ID/Serial: {clean(device_id)} | "
            f"Manufacturer: {clean(info.get('manufacturer', 'Unknown'))} | "
            f"Model: {clean(info.get('model', 'Unknown'))} | "
            f"Product Name: {clean(info.get('product_name', 'Unknown'))} | "
            f"Android Version: {clean(info.get('android_version', 'Unknown'))} (Codename: {clean(info.get('android_codename', 'Unknown'))}, Build ID: {clean(info.get('build_id', 'Unknown'))}) | "
            f"Linux Kernel: {clean(info.get('kernel', 'Unknown'))} | "
            f"CPU/SoC: {clean(info.get('cpu', 'Unknown'))} | "
            f"RAM: {clean(info.get('ram', 'Unknown'))} | "
            f"Display: {clean(display_info)} | "
            f"Battery: {clean(battery_info)} | "
            f"Storage & Partition Free Space: {clean(storage_info.get('summary', 'Unknown'))} | "
            f"Active Running Processes ({len(processes)} total): [{proc_formatted}] | "
            f"Installed Applications ({len(apps)} total packages): [{apps_formatted}]."
        )

        update_p(100, "Report generation complete.")
        return report_paragraph

    def is_directory_writable(self, device_id: str, path: str) -> bool:
        """Check dynamically if a directory on the device is writable."""
        try:
            res = self._run_command(['shell', f'[ -w "{path}" ] && echo 1 || echo 0'], device_id)
            return res.strip() == '1'
        except Exception:
            return False

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

    def extract_app_icon(self, device_id: str, package: str, output_dir: str) -> Optional[str]:
        """Extract application icon from base/system/split APK on device and save to output_dir.
        Returns the local filepath of the extracted PNG, or None if failed.
        """
        import os
        try:
            _validate_package(package)
            # Purge icon cache files older than 7 days
            self.cleanup_icon_cache(output_dir, max_age_days=7)


            # 1. Get all APK paths on device for package

            path_output = self._run_command(['shell', 'pm', 'path', package], device_id)
            apk_paths = []
            for line in path_output.split('\n'):
                line = line.strip()
                if line.startswith('package:'):
                    p = line.replace('package:', '').strip()
                    if p.endswith('.apk'):
                        apk_paths.append(p)
            
            if not apk_paths:
                return None
                
            # Sort paths to prefer base.apk or split_config first if available
            apk_paths.sort(key=lambda x: 0 if 'base.apk' in x else (1 if 'split_config' in x else 2))
            
            # 2. List zip contents across all APKs
            all_candidates = [] # list of (score, file_path, apk_path)
            for apk_path in apk_paths:
                try:
                    list_output = self._run_command(['shell', 'unzip', '-l', f'"{apk_path}"'], device_id)
                    for line in list_output.split('\n'):
                        line = line.strip()
                        if not line or not (line.endswith('.png') or line.endswith('.webp')):
                            continue
                        parts = line.split()
                        if len(parts) < 4:
                            continue
                        file_path = parts[-1]
                        
                        score = 0
                        filename = os.path.basename(file_path).lower()
                        
                        if filename in ('ic_launcher_foreground.png', 'ic_launcher_foreground.webp'):
                            score += 120
                        elif filename in ('ic_launcher.png', 'ic_launcher.webp'):
                            score += 100
                        elif 'ic_launcher_foreground' in filename:
                            score += 90
                        elif 'ic_launcher' in filename:
                            score += 50
                        elif 'launcher' in filename:
                            score += 40
                        elif 'icon' in filename:
                            score += 20
                        elif 'logo' in filename:
                            score += 15
                            
                        if 'monochrome' in filename or 'background' in filename:
                            score -= 50
                        
                        if 'xxhdpi' in file_path:
                            score += 15
                        elif 'xhdpi' in file_path:
                            score += 12
                        elif 'xxxhdpi' in file_path:
                            score += 10
                        elif 'hdpi' in file_path:
                            score += 8
                        elif 'mdpi' in file_path:
                            score += 5
                            
                        if score > 0:
                            all_candidates.append((score, file_path, apk_path))
                except Exception:
                    continue
                
            if not all_candidates:
                return None
                
            all_candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_candidate, target_apk_path = all_candidates[0]
                
            # 3. Extract chosen PNG/WebP to local output_dir
            local_icon_path = os.path.join(output_dir, f"{package}_icon.png")
            os.makedirs(output_dir, exist_ok=True)
            
            # Remove existing local icon to avoid returning stale files if extraction fails
            if os.path.exists(local_icon_path):
                try:
                    os.remove(local_icon_path)
                except Exception:
                    pass

            unique_id = uuid.uuid4().hex[:8]
            device_temp_dir = f"/data/local/tmp/droidmgr_icon_{package}_{unique_id}"
            
            try:
                self._run_command(['shell', 'unzip', '-o', f'"{target_apk_path}"', f'"{best_candidate}"', '-d', device_temp_dir], device_id)
                device_icon_path = f"{device_temp_dir}/{best_candidate}"
                self.download_file(device_id, device_icon_path, local_icon_path)
                
                if os.path.exists(local_icon_path) and os.path.getsize(local_icon_path) > 0:
                    return local_icon_path
            finally:
                try:
                    self._run_command(['shell', 'rm', '-rf', device_temp_dir], device_id)
                except Exception:
                    pass
                    
        except Exception:
            pass
        return None





