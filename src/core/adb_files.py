"""ADBManager mixin: directory listing and file transfer primitives."""

import hashlib
import os
import posixpath
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from .adb_base import ADBCommandError
from .audit_logger import AuditLogger


class _FilesMixin:
    """_FilesMixin for ADBManager (see adb_manager.py)."""

    PROTECTED_PATHS = {
        '/', '/system', '/system/app', '/system/priv-app', '/system/bin', '/system/etc',
        '/data', '/proc', '/dev', '/sbin', '/vendor', '/product', '/system_ext',
        '/odm', '/apex', '/sys', '/etc', '/bin', '/mnt', '/root'
    }

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

        return self._parse_ls_output(output, path, show_hidden, use_exact_sizes)

    def list_dir(self, device_id: str, path: str = '/sdcard/', show_hidden: bool = True,
                 use_exact_sizes: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        """List a directory and probe writability in a single adb round trip.

        Navigation used to cost two round trips (ls, then a [ -w ] probe);
        each `adb shell` spawns a fresh connection, so halving the trips
        roughly halves navigation latency. Returns (files, is_writable).
        """
        if not path.strip():
            path = "/"
        if not path.endswith('/'):
            path += '/'

        qp = self._sh_quote(path)
        script = (f'ls -la {qp} 2>&1; echo __DROIDMGR_WR__:$([ -w {qp} ] && echo 1 || echo 0)')
        try:
            output = self._run_command(['shell', script], device_id)
        except RuntimeError as e:
            if "No such file or directory" in str(e):
                return [], False
            raise e

        # The script always exits 0 (echo is last), so detect ls errors
        # in the merged output instead of via the return code.
        if 'No such file or directory' in output:
            return [], False
        if 'Permission denied' in output:
            raise ADBCommandError(f"ADB command failed: Permission denied: {path}")

        writable = False
        ls_lines = []
        for line in output.splitlines():
            if line.startswith('__DROIDMGR_WR__:'):
                writable = line.split(':', 1)[1].strip() == '1'
            else:
                ls_lines.append(line)
        files = self._parse_ls_output('\n'.join(ls_lines), path, show_hidden, use_exact_sizes)
        return files, writable

    def _parse_ls_output(self, output: str, path: str, show_hidden: bool, use_exact_sizes: bool) -> List[Dict[str, Any]]:
        """Parse one `ls -la` listing into file dicts (shared by list_files/list_dir)."""
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

    @staticmethod
    def _sh_quote(value: str) -> str:
        """Quote one string for POSIX sh double quotes (escape specials)."""
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'

    def get_empty_dirs(self, device_id: str, path: str) -> set:
        """Names of immediate subdirectories of path that contain no entries.

        One adb round trip for the whole directory: the shell glob enumerates
        subdirs (names never leave the device, so no quoting issues) and only
        the "empty" verdicts come back. Unparseable or failed output means an
        empty set, so callers show the normal folder icon as a safe default.
        """
        query = (path.rstrip('/') or '/') + '/'
        script = (
            f'cd {self._sh_quote(query)} 2>/dev/null || exit 0;'
            ' for d in */; do [ -e "$d" ] || continue;'
            ' if [ -z "$(ls -A -- "$d" 2>/dev/null | head -n 1)" ]; then'
            ' printf "E\\t%s\\n" "${d%/}"; fi; done;'
            ' for d in .*/; do case "$d" in "./"|"../") continue;; esac;'
            ' [ -e "$d" ] || continue;'
            ' if [ -z "$(ls -A -- "$d" 2>/dev/null | head -n 1)" ]; then'
            ' printf "E\\t%s\\n" "${d%/}"; fi; done'
        )
        try:
            output = self._run_command(['shell', script], device_id)
        except Exception:
            return set()
        empty = set()
        for line in (output or '').splitlines():
            if line.startswith('E\t'):
                empty.add(line[2:])
        return empty

    def download_file(self, device_id: str, remote_path: str, local_path: str) -> None:
        self._run_command(['pull', remote_path, local_path], device_id)

    @staticmethod
    def _safe_ntfs_component(component: str) -> str:
        """Escape Windows-invalid names without making distinct Android names collide."""
        original = component or '_'
        encoded = []
        invalid = '<>:"/\\|?*%'
        for index, char in enumerate(original):
            is_trailing_dot_or_space = index == len(original) - 1 and char in '. '
            if char in invalid or ord(char) < 32 or is_trailing_dot_or_space:
                encoded.extend(f'%{byte:02X}' for byte in char.encode('utf-8'))
            else:
                encoded.append(char)
        safe = ''.join(encoded)
        if re.match(r'^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?$', safe, re.IGNORECASE):
            first = safe[0].encode('utf-8')
            safe = ''.join(f'%{byte:02X}' for byte in first) + safe[1:]

        max_units = 240
        if len(safe.encode('utf-16-le')) // 2 > max_units:
            suffix = '~' + hashlib.sha256(original.encode('utf-8', errors='replace')).hexdigest()[:10]
            shortened = []
            units = 0
            for char in safe:
                char_units = len(char.encode('utf-16-le')) // 2
                if units + char_units + len(suffix) > max_units:
                    break
                shortened.append(char)
                units += char_units
            safe = ''.join(shortened) + suffix
        return safe or '_'

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



    def is_directory_writable(self, device_id: str, path: str) -> bool:
        """Check dynamically if a directory on the device is writable."""
        try:
            res = self._run_command(['shell', f'[ -w "{path}" ] && echo 1 || echo 0'], device_id)
            return res.strip() == '1'
        except Exception:
            return False

