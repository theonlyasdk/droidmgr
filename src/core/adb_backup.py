"""ADBManager mixin: full-filesystem backup, estimates and uploads."""

import hashlib
import json
import os
import posixpath
import queue
import shlex
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from .adb_base import ADBCommandError


class _BackupMixin:
    """_BackupMixin for ADBManager (see adb_manager.py)."""

    def backup_filesystem(self, device_id: str, destination: str, cancel_event, progress_callback=None,
                          remote_root: str = '/', parallelism: int = 4, exclusions=None, only_paths=None,
                          verify_checksums=False) -> bool:
        """Index one device storage area, then download its files with a small worker pool."""
        roots = ['/system', '/vendor', '/product', '/system_ext', '/odm', '/apex'] if remote_root == 'system' else [remote_root]
        os.makedirs(destination, exist_ok=True)
        exclusions = [path.rstrip('/') for path in (exclusions or []) if isinstance(path, str) and path.startswith('/')]
        if only_paths is not None:
            paths = list(only_paths)
        else:
            command = [self.adb_path, '-s', device_id, 'shell', 'find', *roots, '-type', 'f']
            paths = []
            scanned = 0
            output_lines = queue.Queue()
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                       encoding='utf-8', errors='replace')
            if hasattr(cancel_event, 'register'):
                cancel_event.register(process)

            def read_index():
                try:
                    for output_line in process.stdout:
                        output_lines.put(output_line)
                finally:
                    output_lines.put(None)

            reader = threading.Thread(target=read_index, daemon=True)
            reader.start()
            try:
                while True:
                    if cancel_event.is_set():
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        return False
                    try:
                        line = output_lines.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    path = line.rstrip('\r\n')
                    excluded = False
                    if path.startswith('/'):
                        scanned += 1
                        excluded = any(path == rule or path.startswith(rule + '/') for rule in exclusions)
                        if not excluded:
                            paths.append(path)
                    if progress_callback and path.startswith('/'):
                        progress_callback('index_skipped' if excluded else 'index', scanned, 0, path, ())
                process.wait()
                if process.returncode and not paths and not cancel_event.is_set():
                    raise ADBCommandError("Could not index device filesystem. Check the device connection and ADB permissions.")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)

            if cancel_event.is_set():
                return False

            cache_path = os.path.join(destination, '.droidmgr_index.json')
            temp_cache_path = cache_path + '.tmp'
            with open(temp_cache_path, 'w', encoding='utf-8') as cache_file:
                json.dump({'device_id': device_id, 'remote_root': remote_root,
                           'exclusions': exclusions, 'files': paths}, cache_file)
            os.replace(temp_cache_path, cache_path)

        if progress_callback:
            progress_callback('indexed', 0, len(paths), '', paths)
        if cancel_event.is_set():
            return False
        total = len(paths)
        if not total:
            if only_paths is None:
                manifest_path = os.path.join(destination, '.droidmgr_backup_manifest.json')
                with open(manifest_path, 'w', encoding='utf-8') as manifest_file:
                    json.dump({'files': []}, manifest_file)
                if progress_callback:
                    progress_callback('verification', 0, 0, '', {
                        'bytes': 0, 'invalid': [], 'failed': [],
                        'checksums': bool(verify_checksums), 'indexed': 0,
                    })
            return True

        pending = list(paths)
        active = set()
        completed = 0
        failures = []
        manifest_lock = threading.Lock()
        manifest = {}
        manifest_path = os.path.join(destination, '.droidmgr_backup_manifest.json')
        if only_paths is not None and os.path.isfile(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as manifest_file:
                    manifest = {row['remote_path']: row for row in json.load(manifest_file).get('files', [])}
            except (OSError, ValueError, KeyError, TypeError):
                manifest = {}
        downloaded_bytes = 0
        byte_rate = 0.0
        byte_rate_sample_time = time.monotonic()
        byte_rate_sample_bytes = 0
        state_lock = threading.Lock()
        target_lock = threading.Lock()
        local_targets = set()

        def local_path_for(remote_path):
            if only_paths is not None and remote_path in manifest:
                return os.path.join(destination, manifest[remote_path]['local_path'])
            components = [self._safe_ntfs_component(part) for part in remote_path.split('/') if part]
            if not components:
                components = ['_']
            target = os.path.join(destination, *components)
            if len(os.path.abspath(target)) > 240:
                digest = hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:24]
                target = os.path.join(destination, '_long_paths', f'{digest}_{components[-1][:80]}')
            with target_lock:
                key = os.path.normcase(target).casefold()
                if key in local_targets:
                    leaf = components[-1]
                    suffix = '~' + hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:10]
                    components[-1] = self._safe_ntfs_component(leaf[:100] + suffix)
                    target = os.path.join(destination, *components)
                    if len(os.path.abspath(target)) > 240:
                        digest = hashlib.sha256(remote_path.encode('utf-8', errors='replace')).hexdigest()[:24]
                        target = os.path.join(destination, '_long_paths', f'{digest}_{components[-1][:80]}')
                    key = os.path.normcase(target).casefold()
                    counter = 1
                    while key in local_targets:
                        components[-1] = self._safe_ntfs_component(leaf[:90] + suffix + f'~{counter}')
                        target = os.path.join(destination, *components)
                        key = os.path.normcase(target).casefold()
                        counter += 1
                local_targets.add(key)
            return target

        def pull_one(remote_path):
            nonlocal completed, downloaded_bytes, byte_rate, byte_rate_sample_time, byte_rate_sample_bytes
            if cancel_event.is_set():
                return False
            with state_lock:
                pending.remove(remote_path)
                active.add(remote_path)
                if progress_callback:
                    progress_callback('download_current', completed, total, '\n'.join(active), list(pending))

            local_path = local_path_for(remote_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            pull = subprocess.Popen([self.adb_path, '-s', device_id, 'pull', remote_path, local_path],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding='utf-8', errors='replace')
            if hasattr(cancel_event, 'register'):
                cancel_event.register(pull)
            try:
                last_size = 0
                while pull.poll() is None:
                    if cancel_event.is_set():
                        pull.kill()
                        pull.wait()
                        pull.communicate()
                        return False
                    try:
                        current_size = os.path.getsize(local_path)
                    except OSError:
                        current_size = 0
                    now = time.monotonic()
                    with state_lock:
                        if current_size > last_size:
                            downloaded_bytes += current_size - last_size
                            last_size = current_size
                        elapsed = now - byte_rate_sample_time
                        if elapsed >= 0.5:
                            byte_rate = (downloaded_bytes - byte_rate_sample_bytes) / elapsed
                            byte_rate_sample_time = now
                            byte_rate_sample_bytes = downloaded_bytes
                            if progress_callback:
                                progress_callback(
                                    'download_rate', completed, total, remote_path,
                                    (downloaded_bytes, byte_rate, list(pending), list(active))
                                )
                    time.sleep(0.1)
                stdout, stderr = pull.communicate()
                if cancel_event.is_set():
                    return False
                if pull.returncode:
                    raise ADBCommandError(f"Could not download {remote_path}: {stderr.strip() or stdout.strip()}")
                size = os.path.getsize(local_path)
                digest = None
                if verify_checksums:
                    hasher = hashlib.sha256()
                    with open(local_path, 'rb') as downloaded_file:
                        for chunk in iter(lambda: downloaded_file.read(1024 * 1024), b''):
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                with state_lock:
                    try:
                        current_size = os.path.getsize(local_path)
                    except OSError:
                        current_size = last_size
                    if current_size > last_size:
                        downloaded_bytes += current_size - last_size
                    completed += 1
                    active.discard(remote_path)
                    with manifest_lock:
                        manifest[remote_path] = {
                            'remote_path': remote_path,
                            'local_path': os.path.relpath(local_path, destination),
                            'size': size,
                            'sha256': digest,
                        }
                    if progress_callback:
                        progress_callback('download', completed, total, remote_path,
                                          (list(pending), list(active), downloaded_bytes))
                return True
            except Exception as exc:
                if cancel_event.is_set():
                    return False
                with state_lock:
                    completed += 1
                    active.discard(remote_path)
                    failures.append((remote_path, str(exc)))
                    if progress_callback:
                        progress_callback('download_failed', completed, total, remote_path,
                                          (str(exc), list(pending), list(active)))
                return False
            finally:
                if pull.poll() is None:
                    pull.kill()
                    pull.wait()
                if hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(pull)

        worker_count = max(1, min(int(parallelism), 16, total))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            path_iterator = iter(paths)
            futures = set()
            for _ in range(worker_count):
                futures.add(executor.submit(pull_one, next(path_iterator)))

            while futures:
                if cancel_event.is_set():
                    return False
                finished, futures = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in finished:
                    try:
                        future.result()
                    except Exception:
                        cancel_event.set()
                        raise
                    if cancel_event.is_set():
                        return False
                    try:
                        next_path = next(path_iterator)
                    except StopIteration:
                        continue
                    futures.add(executor.submit(pull_one, next_path))
        if not cancel_event.is_set():
            temp_manifest = manifest_path + '.tmp'
            with open(temp_manifest, 'w', encoding='utf-8') as manifest_file:
                json.dump({'files': list(manifest.values())}, manifest_file, indent=2)
            os.replace(temp_manifest, manifest_path)
            if progress_callback:
                progress_callback('verification_start', 0, len(manifest), '', ())
            verified = 0
            invalid = []
            verified_bytes = 0
            for record in manifest.values():
                local_path = os.path.join(destination, record['local_path'])
                try:
                    if os.path.getsize(local_path) != record['size']:
                        raise OSError('file size changed')
                    if record.get('sha256'):
                        hasher = hashlib.sha256()
                        with open(local_path, 'rb') as downloaded_file:
                            for chunk in iter(lambda: downloaded_file.read(1024 * 1024), b''):
                                hasher.update(chunk)
                        if hasher.hexdigest() != record['sha256']:
                            raise OSError('SHA-256 mismatch')
                    verified += 1
                    verified_bytes += record['size']
                except OSError as exc:
                    invalid.append((record['remote_path'], str(exc)))
            if progress_callback:
                progress_callback('verification', verified, len(manifest), '',
                                  {'bytes': verified_bytes, 'invalid': invalid,
                                   'failed': failures, 'checksums': bool(verify_checksums),
                                   'indexed': total})
        if progress_callback:
            progress_callback('download_summary', len(failures), total, '', failures)
        return not cancel_event.is_set()

    def estimate_filesystem_size(self, device_id: str, remote_root: str = '/', cancel_event=None) -> Optional[int]:
        """Return a conservative device-side `du` estimate in bytes, or None if unavailable."""
        roots = ['/system', '/vendor', '/product', '/system_ext', '/odm', '/apex'] if remote_root == 'system' else [remote_root]
        try:
            process = subprocess.Popen(
                [self.adb_path, '-s', device_id, 'shell', 'du', '-sk', *roots],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding='utf-8', errors='replace',
            )
            if cancel_event is not None and hasattr(cancel_event, 'register'):
                cancel_event.register(process)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if ((cancel_event is not None and cancel_event.is_set())
                            or time.monotonic() - started > 45):
                        process.kill()
                        process.wait()
                        process.communicate()
                        return None
                    time.sleep(0.05)
                stdout, _stderr = process.communicate()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if cancel_event is not None and hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)
            if cancel_event is not None and cancel_event.is_set():
                return None
            sizes = []
            for line in stdout.splitlines():
                parts = line.strip().split(None, 1)
                if parts and parts[0].isdigit():
                    sizes.append(int(parts[0]) * 1024)
            return sum(sizes) if sizes else None
        except (OSError, subprocess.SubprocessError):
            return None

    def upload_file(self, device_id: str, local_path: str, remote_path: str, cancel_event=None) -> None:
        def run(args, failure_message):
            process = subprocess.Popen([self.adb_path, '-s', device_id, *args],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='replace')
            if cancel_event is not None and hasattr(cancel_event, 'register'):
                cancel_event.register(process)
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        process.communicate()
                        return False
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancel_event is not None and cancel_event.is_set():
                    return False
                if process.returncode:
                    raise ADBCommandError(f"{failure_message}: {stderr.strip() or stdout.strip()}")
                return True
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if cancel_event is not None and hasattr(cancel_event, 'unregister'):
                    cancel_event.unregister(process)

        parent = posixpath.dirname(remote_path)
        if parent and not run(['shell', f'mkdir -p {shlex.quote(parent)}'],
                              f"Could not prepare restore path {parent}"):
            return
        run(['push', local_path, remote_path], f"Could not restore {remote_path}")

