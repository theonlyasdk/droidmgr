"""MainWindow mixin: restore-from-backup flow."""

import json
import os
import re
import shutil
import stat
import tempfile
import threading
import tkinter as tk
import zipfile
from pathlib import Path, PurePosixPath
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .backup_dialog import BackupCancelToken, BackupOptionsDialog, BackupProgressDialog, RestoreSelectionDialog


class _RestoreMixin:
    """_RestoreMixin for MainWindow (see main_window.py)."""

    def _restore_from_backup(self):
        if not self._require_device():
            return
        choose_zip = messagebox.askyesnocancel(
            "Choose Backup Source", "Restore from a ZIP archive?\n\nChoose No to select a backup folder.", parent=self.root
        )
        if choose_zip is None:
            return
        if choose_zip:
            archive_path = filedialog.askopenfilename(
                parent=self.root, title="Select Backup ZIP", filetypes=(("ZIP archives", "*.zip"), ("All files", "*.*"))
            )
            if not archive_path:
                return
            source_root = Path(archive_path)
            try:
                with zipfile.ZipFile(source_root) as archive:
                    remote_by_local = {}
                    try:
                        manifest = json.loads(archive.read('.droidmgr_backup_manifest.json').decode('utf-8'))
                        remote_by_local = {row['local_path'].replace('\\', '/'): row['remote_path']
                                           for row in manifest.get('files', [])}
                    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
                        pass
                    candidates = []
                    for info in archive.infolist():
                        if info.is_dir() or info.filename.endswith('.droidmgr_index.json') or info.filename.endswith('.droidmgr_backup_manifest.json'):
                            continue
                        member = PurePosixPath(info.filename)
                        if member.is_absolute() or not member.parts or any(part in ('', '.', '..') for part in member.parts):
                            continue
                        mode = info.external_attr >> 16
                        if stat.S_ISLNK(mode):
                            continue
                        remote = remote_by_local.get(member.as_posix(), '/' + member.as_posix())
                        remote_parts = PurePosixPath(remote).parts
                        if not remote.startswith('/') or any(part == '..' for part in remote_parts):
                            continue
                        candidates.append((remote, ('zip', str(source_root), info.filename)))
            except (OSError, zipfile.BadZipFile) as exc:
                self._show_error("Restore Error", f"Could not read this ZIP archive:\n{exc}")
                return
        else:
            folder = filedialog.askdirectory(parent=self.root, title="Select Backup Folder")
            if not folder:
                return
            source_root = Path(folder)
            candidates = []
            remote_by_local = {}
            try:
                manifest = json.loads((source_root / '.droidmgr_backup_manifest.json').read_text(encoding='utf-8'))
                remote_by_local = {row['local_path'].replace('\\', '/'): row['remote_path']
                                   for row in manifest.get('files', [])}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            if remote_by_local:
                for relative, remote in remote_by_local.items():
                    if PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts:
                        continue
                    local_path = source_root / Path(relative)
                    if local_path.is_file() and remote.startswith('/') and '..' not in PurePosixPath(remote).parts:
                        candidates.append((remote, ('file', str(local_path), None)))
            else:
                for path in source_root.rglob('*'):
                    if not path.is_file() or path.name.startswith('.droidmgr_'):
                        continue
                    relative = path.relative_to(source_root).as_posix()
                    member = PurePosixPath(relative)
                    if member.is_absolute() or any(part in ('', '.', '..') for part in member.parts):
                        continue
                    candidates.append(('/' + member.as_posix(), ('file', str(path), None)))
        if not candidates:
            messagebox.showinfo("No Backup Files", "No restorable files were found in that backup.", parent=self.root)
            return
        selected = RestoreSelectionDialog(self.root, candidates).result
        if not selected:
            return
        if not messagebox.askyesno(
            "Confirm Restore",
            f"Copy {len(selected):,} selected files to {self.selected_device}? Existing device files at those paths may be overwritten.",
            parent=self.root,
        ):
            return
        cancel_event = BackupCancelToken()
        dialog = BackupProgressDialog(self.root, f"Restoring to {self.selected_device}", cancel_event)
        dialog.set_queue([remote for remote, _source in selected], "restore")
        self.taskbar_progress.set_indeterminate()
        self._restore_batch(dialog, self.selected_device, selected, cancel_event)

    def _restore_batch(self, dialog, device_id, selected, cancel_event):
        cancel_event.clear()
        failures = []
        total = len(selected)
        dialog.set_queue([remote for remote, _source in selected], "restore")

        def task():
            completed = 0
            for index, (remote, source) in enumerate(selected):
                if cancel_event.is_set():
                    break
                pending_paths = [item[0] for item in selected[index + 1:]]
                self.root.after(0, lambda d=completed, t=total, p=remote, pending=pending_paths:
                                dialog.set_current_download(d, t, p, pending))
                temp_path = None
                try:
                    kind, location, member = source
                    local_path = location
                    if kind == 'zip':
                        with zipfile.ZipFile(location) as archive, archive.open(member) as source_file:
                            with tempfile.NamedTemporaryFile(prefix='droidmgr-restore-', delete=False) as temp_file:
                                temp_path = temp_file.name
                                shutil.copyfileobj(source_file, temp_file, 1024 * 1024)
                        local_path = temp_path
                    self.device_manager.upload_file(device_id, local_path, remote, cancel_event)
                    if cancel_event.is_set():
                        break
                    completed += 1
                    self.root.after(0, lambda d=completed, t=total: self.taskbar_progress.set_value(d, t))
                    self.root.after(0, lambda d=completed, t=total, p=remote, pending=[item[0] for item in selected[index + 1:]]:
                                    dialog.set_download(d, t, p, (pending, [], 0)))
                except Exception as exc:
                    failures.append((remote, str(exc)))
                    completed += 1
                    self.root.after(0, lambda d=completed, t=total, p=remote, e=str(exc):
                                    dialog.set_failed(d, t, p, e))
                finally:
                    if temp_path:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass
            self.root.after(0, lambda: self._restore_batch_done(dialog, device_id, selected, failures, cancel_event))

        threading.Thread(target=task, daemon=True).start()

    def _restore_batch_done(self, dialog, device_id, selected, failures, cancel_event):
        if cancel_event.is_set():
            self.taskbar_progress.clear()
            dialog.finish("Restore canceled. Files already copied remain on the device.", close_after_ms=600)
            return
        if failures:
            summary = "Some files could not be restored:\n\n" + "\n".join(
                f"{remote}: {error}" for remote, error in failures[:30]
            )
            if len(failures) > 30:
                summary += f"\n...and {len(failures) - 30} more."
            if messagebox.askyesno("Retry Failed Files?", summary + "\n\nRetry the failed files?", parent=dialog):
                failed_paths = {remote for remote, _error in failures}
                self._restore_batch(dialog, device_id,
                                    [item for item in selected if item[0] in failed_paths], cancel_event)
                return
            messagebox.showinfo("Restore Summary", summary, parent=dialog)
            self.taskbar_progress.clear()
            dialog.finish(f"Restore finished with {len(failures):,} failed files.")
        else:
            self.taskbar_progress.clear()
            dialog.finish(f"Restored {len(selected):,} files to {device_id}.")

    def _retry_backup_failures(self, dialog, backup_sets, failed_by_folder, cancel_event,
                               parallelism, verify_checksums, verification_by_folder):
        retries = {folder: list(items) for folder, items in failed_by_folder.items() if items}
        if not retries:
            return
        cancel_event.clear()
        failed_again = {str(folder): [] for _, _, folder in backup_sets}
        for section, _remote_root, folder in backup_sets:
            for remote, _error in retries.get(str(folder), []):
                row = dialog._queue_indexes.get(remote)
                if row is not None:
                    dialog.queue.delete(row)
                    dialog.queue.insert(row, remote)
            paths = [remote for remote, _error in retries.get(str(folder), [])]
            if paths:
                dialog.set_queue(paths, section)
                self.taskbar_progress.set_value(0, len(paths))

        def retry_task():
            try:
                for section, root_path, folder in backup_sets:
                    paths = [remote for remote, _error in retries.get(str(folder), [])]
                    if not paths or cancel_event.is_set():
                        continue

                    def progress(stage, done, total, path, details):
                        if stage == 'download':
                            self.root.after(0, lambda d=done, t=total: self.taskbar_progress.set_value(d, t))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_download(d, t, p, r))
                        elif stage == 'download_current':
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_current_download(d, t, p, r))
                        elif stage == 'download_failed':
                            failed_again[str(folder)].append((path, details[0]))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details[0]:
                                            dialog.set_failed(d, t, p, r))
                        elif stage == 'download_rate':
                            self.root.after(0, lambda d=done, t=total: self.taskbar_progress.set_value(d, t))
                            self.root.after(0, lambda d=done, t=total, p=path, r=details:
                                            dialog.set_download_rate(d, t, p, r))
                        elif stage == 'verification':
                            result = dict(details)
                            result['verified'] = done
                            result['indexed'] = verification_by_folder.get(str(folder), {}).get(
                                'indexed', result.get('indexed', done)
                            )
                            self.root.after(0, lambda r=result, key=str(folder): verification_by_folder.__setitem__(key, r))
                        elif stage == 'verification_start':
                            self.root.after(0, self.taskbar_progress.set_indeterminate)

                    self.device_manager.backup_filesystem(
                    self.selected_device, str(folder), cancel_event, progress,
                        root_path, parallelism, [], paths, verify_checksums
                    )
                remaining = [(folder, remote, error) for folder, items in failed_again.items()
                             for remote, error in items]
                self.root.after(0, lambda: self._retry_backup_done(
                    dialog, backup_sets, cancel_event, failed_again, remaining, parallelism, verify_checksums
                    , verification_by_folder
                ))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc): self._backup_failed(dialog, error))

        threading.Thread(target=retry_task, daemon=True).start()

    def _retry_backup_done(self, dialog, backup_sets, cancel_event, failed_by_folder, remaining,
                           parallelism, verify_checksums, verification_by_folder):
        if cancel_event.is_set():
            self.taskbar_progress.clear()
            dialog.finish("Retry canceled. Downloaded files were kept.", close_after_ms=600)
            return
        if remaining:
            summary = "Still unable to download:\n\n" + "\n".join(
                f"{remote}: {error}" for _folder, remote, error in remaining[:30]
            )
            if len(remaining) > 30:
                summary += f"\n...and {len(remaining) - 30} more."
            if messagebox.askyesno("Retry Failed Files?", summary + "\n\nTry these files again?", parent=dialog):
                self._retry_backup_failures(dialog, backup_sets, failed_by_folder, cancel_event,
                                            parallelism, verify_checksums, verification_by_folder)
                return
            messagebox.showinfo("Backup File Summary", summary, parent=dialog)
        self._backup_download_done(dialog, backup_sets, cancel_event, True,
                                   re.sub(r'\s+', '', self.selected_device or 'device'),
                                   failed_by_folder, parallelism, verify_checksums,
                                   verification_by_folder, allow_retry=False)

