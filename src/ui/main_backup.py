"""MainWindow mixin: backup-to-archive flow."""

import os
import queue
import re
import shutil
import stat
import threading
import tkinter as tk
import zipfile
from pathlib import Path, PurePosixPath
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .backup_dialog import BackupCancelToken, BackupOptionsDialog, BackupProgressDialog, RestoreSelectionDialog


class _BackupMixin:
    """_BackupMixin for MainWindow (see main_window.py)."""

    def _backup_to_archive(self):
        if not self._require_device():
            return
        device_id = self.selected_device
        safe_id = re.sub(r'\s+', '', device_id)
        safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe_id).rstrip(' .') or 'device'
        if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', safe_id, re.IGNORECASE):
            safe_id = f'_{safe_id}'
        options = BackupOptionsDialog(
            self.root,
            self.config.get('backup', 'scope', 0),
            self.config.get('backup', 'parallelism', 4),
        ).result
        if options is None:
            return
        choice, parallelism = options
        self.config.set('backup', 'scope', choice)
        self.config.set('backup', 'parallelism', parallelism)
        verify_checksums = bool(self.config.get('backup', 'verify_checksums', False))
        exclusions = self.config.get('backup', 'exclude_paths', [])
        if not isinstance(exclusions, list):
            exclusions = []
        downloads_dir = Path.home() / 'Downloads'
        downloads_dir.mkdir(parents=True, exist_ok=True)
        backup_sets = [("internal storage (/storage/emulated/0)", '/storage/emulated/0', downloads_dir / f'{safe_id}_backup_progress')]
        if choice == 1:
            backup_sets.append(("system storage", 'system', downloads_dir / f'{safe_id}_system_backup_progress'))
        existing_dirs = [folder for _, _, folder in backup_sets if folder.exists()]
        if existing_dirs:
            if not messagebox.askyesno(
                "Replace Backup Folder?",
                "These backup folders already exist. Replace them?\n\n" + "\n".join(str(p) for p in existing_dirs),
                parent=self.root,
            ):
                return
            try:
                for folder in existing_dirs:
                    shutil.rmtree(folder)
            except OSError as exc:
                self._show_error("Backup Error", f"Could not replace the existing folder:\n{exc}")
                return

        cancel_event = BackupCancelToken()
        indexed_ack = threading.Event()
        index_started = threading.Event()
        progress_events = queue.Queue()
        failed_by_folder = {str(folder): [] for _, _, folder in backup_sets}
        verification_by_folder = {}
        poll_active = [True]
        dialog = BackupProgressDialog(self.root, f"Backing Up {device_id}", cancel_event)

        def poll_progress_events():
            index_updates = []

            def flush_index_updates():
                if index_updates:
                    section = index_updates[-1][0]
                    included = [item[2] for item in index_updates if item[3]]
                    dialog.add_indexed_paths(index_updates[-1][1], included, section, index_updates[-1][2])
                    index_updates.clear()

            for _ in range(500):
                try:
                    event = progress_events.get_nowait()
                except queue.Empty:
                    break
                stage = event[0]
                if stage == 'index':
                    index_updates.append((event[1], event[2], event[3], True))
                    continue
                if stage == 'index_skipped':
                    index_updates.append((event[1], event[2], event[3], False))
                    continue
                flush_index_updates()
                if stage == 'index_start':
                    dialog.start_indexing(event[1])
                    self.taskbar_progress.set_indeterminate()
                    event[2].set()
                elif stage == 'indexed':
                    dialog.set_queue(event[2], event[1])
                    self.taskbar_progress.set_value(0, len(event[2]))
                    dialog.status.config(text=f"Estimating size for {event[1]}...")
                    def check_space(section=event[1], root=event[4], ack=event[3]):
                        try:
                            estimate = self.device_manager.estimate_filesystem_size(device_id, root, cancel_event)
                            free = shutil.disk_usage(downloads_dir).free
                        except OSError:
                            estimate, free = None, 0
                        def continue_after_check():
                            if not dialog.winfo_exists():
                                cancel_event.set()
                                ack.set()
                                return
                            if estimate is not None and estimate > free:
                                estimate_text = BackupProgressDialog._format_byte_rate(estimate).replace('/s', '')
                                free_text = BackupProgressDialog._format_byte_rate(free).replace('/s', '')
                                proceed = messagebox.askyesno(
                                    "Low Disk Space",
                                    f"Estimated backup size: {estimate_text}\nAvailable space: {free_text}\n\nContinue anyway?",
                                    parent=dialog,
                                )
                                if not proceed:
                                    cancel_event.set()
                            ack.set()
                        self.root.after(0, continue_after_check)
                    threading.Thread(target=check_space, daemon=True).start()
                elif stage == 'download_current':
                    dialog.set_current_download(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                    dialog.update_idletasks()
                elif stage == 'download':
                    dialog.set_download(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                    dialog.update_idletasks()
                elif stage == 'download_rate':
                    dialog.set_download_rate(event[1], event[2], event[3], event[4])
                    self.taskbar_progress.set_value(event[1], event[2])
                elif stage == 'download_failed':
                    dialog.set_failed(event[1], event[2], event[3], event[4][0])
                elif stage == 'verification':
                    verification_by_folder[event[1]] = event[2]
                    dialog.status.config(text=f"Verified {event[2].get('verified', 0):,} files; "
                                              f"{len(event[2].get('invalid', [])):,} size/checksum errors")
                elif stage == 'verification_start':
                    dialog.status.config(text="Verifying downloaded file sizes and checksums...")
                    self.taskbar_progress.set_indeterminate()
                elif stage == 'done':
                    poll_active[0] = False
                    self._backup_download_done(dialog, event[1], event[2], event[3], event[4], event[5],
                                               event[6], event[7], event[8])
                elif stage == 'error':
                    poll_active[0] = False
                    self._backup_failed(dialog, event[1])
            flush_index_updates()
            if poll_active[0] and dialog.winfo_exists():
                dialog.after(10 if not progress_events.empty() else 50, poll_progress_events)

        dialog.after(50, poll_progress_events)

        def make_progress(section, backup_dir, root_path):
            def progress(stage, done, total, path, paths, indexed_root=root_path):
                if stage == 'index':
                    progress_events.put(('index', section, done, path))
                elif stage == 'index_skipped':
                    progress_events.put(('index_skipped', section, done, path))
                elif stage == 'indexed':
                    progress_events.put(('indexed', section, paths, indexed_ack, indexed_root))
                    indexed_ack.wait()
                elif stage == 'download_current':
                    progress_events.put(('download_current', done, total, path, paths))
                elif stage == 'download':
                    progress_events.put(('download', done, total, path, paths))
                elif stage == 'download_rate':
                    progress_events.put(('download_rate', done, total, path, paths))
                elif stage == 'download_failed':
                    failed_by_folder[str(backup_dir)].append((path, paths[0]))
                    progress_events.put(('download_failed', done, total, path, paths))
                elif stage == 'verification':
                    result = dict(paths)
                    result['verified'] = done
                    verification_by_folder[str(backup_dir)] = result
                    progress_events.put(('verification', str(backup_dir), result))
                elif stage == 'verification_start':
                    progress_events.put(('verification_start',))
            return progress

        def backup_task():
            try:
                completed = True
                for section, root_path, backup_dir in backup_sets:
                    if cancel_event.is_set():
                        completed = False
                        break
                    progress_events.put(('index_start', section, index_started))
                    index_started.wait()
                    index_started.clear()
                    indexed_ack.clear()
                    completed = self.device_manager.backup_filesystem(
                        device_id, str(backup_dir), cancel_event, make_progress(section, backup_dir, root_path),
                        root_path, parallelism, exclusions, None, verify_checksums
                    )
                    if not completed:
                        break
                progress_events.put(('done', backup_sets, cancel_event, completed, safe_id,
                                     failed_by_folder, parallelism, verify_checksums, verification_by_folder))
            except Exception as exc:
                progress_events.put(('error', str(exc)))

        threading.Thread(target=backup_task, daemon=True).start()

    def _backup_download_done(self, dialog, backup_sets, cancel_event, completed, safe_id,
                              failed_by_folder, parallelism, verify_checksums, verification_by_folder,
                              allow_retry=True):
        if not dialog.winfo_exists():
            return
        backup_dirs = [folder for _, _, folder in backup_sets]
        if not completed:
            self.taskbar_progress.clear()
            dialog.finish("Backup canceled. Downloaded files were kept.", close_after_ms=600)
            return
        failures = [(folder, remote, error) for folder, items in failed_by_folder.items()
                    for remote, error in items]
        for folder, result in verification_by_folder.items():
            for remote, error in result.get('invalid', []):
                if not any(existing_remote == remote for _folder, existing_remote, _reason in failures):
                    failures.append((folder, remote, error))
                    failed_by_folder.setdefault(folder, []).append((remote, error))
        verification_lines = []
        for folder, result in verification_by_folder.items():
            invalid = result.get('invalid', [])
            checksum_note = " with SHA-256" if result.get('checksums') else " (file sizes)"
            checked = BackupProgressDialog._format_byte_rate(result.get('bytes', 0)).replace('/s', '')
            verification_lines.append(
                f"{folder}: {result.get('verified', 0):,}/{result.get('indexed', result.get('verified', 0)):,} files verified{checksum_note}; "
                f"{len(invalid):,} mismatches; {checked} checked"
            )
        if verification_lines:
            messagebox.showinfo("Backup Verification", "\n".join(verification_lines), parent=dialog)
        if failures:
            summary = "Some files could not be downloaded:\n\n" + "\n".join(
                f"{remote}: {error}" for _folder, remote, error in failures[:30]
            )
            if len(failures) > 30:
                summary += f"\n...and {len(failures) - 30} more."
            if allow_retry and messagebox.askyesno("Retry Failed Files?", summary + "\n\nRetry the failed files now?", parent=dialog):
                self._retry_backup_failures(dialog, backup_sets, failed_by_folder, cancel_event,
                                            parallelism, verify_checksums, verification_by_folder)
                return
            if not allow_retry:
                summary += "\n\nBackup is partial. The rest of the backup is available."
            messagebox.showinfo("Backup File Summary", summary, parent=dialog)
        sections = [name for name, _, _ in backup_sets]
        if not messagebox.askyesno(
            "Create ZIP Archive?",
            "Backup finished. Create separate ZIP archives for " + " and ".join(sections) + " and remove the staging folders?",
            parent=dialog,
        ):
            self.taskbar_progress.clear()
            dialog.finish("Backups saved to:\n" + "\n".join(str(folder) for folder in backup_dirs))
            return

        cancel_event.clear()
        archive_paths = [
            Path.home() / 'Downloads' / f"{safe_id}_{'internal_storage' if i == 0 else 'system_storage'}_backup.zip"
            for i in range(len(backup_sets))
        ]
        existing_archives = [path for path in archive_paths if path.exists()]
        if existing_archives and not messagebox.askyesno(
            "Replace Archives?",
            "These ZIP archives already exist. Replace them?\n\n" + "\n".join(str(p) for p in existing_archives),
            parent=dialog,
        ):
            self.taskbar_progress.clear()
            dialog.finish("Backups saved to:\n" + "\n".join(str(folder) for folder in backup_dirs))
            return

        def zip_task():
            created_archives = []
            try:
                all_files = [path for folder in backup_dirs for path in folder.rglob('*')
                             if path.is_file() and path.name != '.droidmgr_index.json']
                total = len(all_files)
                done = 0
                for backup_dir, archive_path in zip(backup_dirs, archive_paths):
                    if archive_path.exists():
                        archive_path.unlink()
                    created_archives.append(archive_path)
                    files = [path for path in backup_dir.rglob('*')
                             if path.is_file() and path.name != '.droidmgr_index.json']
                    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for path in files:
                            if cancel_event.is_set():
                                raise InterruptedError("Archive creation canceled")
                            arcname = path.relative_to(backup_dir).as_posix()
                            with path.open('rb') as source, archive.open(arcname, 'w') as target:
                                while True:
                                    if cancel_event.is_set():
                                        raise InterruptedError("Archive creation canceled")
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    target.write(chunk)
                            done += 1
                            self.root.after(0, lambda i=done, n=total, p=path: self._set_archive_progress(dialog, i, n, p))
                if cancel_event.is_set():
                    raise InterruptedError("Archive creation canceled")
                for backup_dir in backup_dirs:
                    shutil.rmtree(backup_dir)
                self.root.after(0, lambda: self._finish_backup(dialog, "Archives saved to:\n" + "\n".join(str(p) for p in archive_paths)))
            except InterruptedError:
                for path in created_archives:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.root.after(0, lambda: self._finish_backup(dialog,
                    "Archive canceled. Backup folders were kept.", close_after_ms=600
                ))
            except Exception as exc:
                for path in created_archives:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.root.after(0, lambda error=str(exc): self._backup_failed(dialog, error))

        dialog.status.config(text="Preparing ZIP archives...")
        dialog.progress.configure(value=0)
        threading.Thread(target=zip_task, daemon=True).start()

    def _backup_failed(self, dialog, error):
        self.taskbar_progress.clear()
        if dialog.winfo_exists():
            dialog.finish("Backup failed. Any downloaded files were kept.")
        self._show_error("Backup Error", error)

    def _set_archive_progress(self, dialog, done, total, path):
        if dialog.winfo_exists():
            dialog.set_archiving(done, total, str(path))
        self.taskbar_progress.set_value(done, total)

    def _finish_backup(self, dialog, message, close_after_ms=None):
        self.taskbar_progress.clear()
        if dialog.winfo_exists():
            dialog.finish(message, close_after_ms=close_after_ms)

