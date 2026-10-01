"""Simple progress window for filesystem backups."""

import tkinter as tk
import threading
import time
from tkinter import ttk
from .dpi import setup_window_dpi


class BackupCancelToken:
    """Cancellation flag that also kills any ADB process currently in flight."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._processes = set()

    def is_set(self):
        return self._event.is_set()

    def register(self, process):
        with self._lock:
            if self._event.is_set():
                try:
                    process.kill()
                except OSError:
                    pass
                return
            self._processes.add(process)

    def unregister(self, process):
        with self._lock:
            self._processes.discard(process)

    def set(self):
        self._event.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            try:
                if process.poll() is None:
                    process.kill()
            except OSError:
                pass

    def clear(self):
        self._event.clear()


class BackupOptionsDialog(tk.Toplevel):
    OPTIONS = ("Internal storage", "Internal storage + system storage")

    def __init__(self, parent, scope=0, parallelism=4):
        super().__init__(parent)
        self.title("Backup Options")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Choose what to back up:").pack(anchor=tk.W, pady=(0, 8))
        self.choice = ttk.Combobox(body, values=self.OPTIONS, state="readonly", width=34)
        self.choice.current(1 if scope == 1 else 0)
        self.choice.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(body, text="Files downloading at once:").pack(anchor=tk.W, pady=(0, 4))
        self.parallelism = ttk.Combobox(body, values=("1", "2", "4", "8"), state="readonly", width=8)
        self.parallelism.set(str(parallelism) if str(parallelism) in ("1", "2", "4", "8") else "4")
        self.parallelism.pack(anchor=tk.W, pady=(0, 12))
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Start", command=self._start).pack(side=tk.RIGHT, padx=(0, 6))

        setup_window_dpi(self, base_width=380, base_height=205, parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.wait_window()

    def _start(self):
        self.result = (self.choice.current(), int(self.parallelism.get()))
        self.destroy()


class BackupProgressDialog(tk.Toplevel):
    def __init__(self, parent, title, cancel_event):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(True, True)
        self.cancel_event = cancel_event
        self.cancelled = False
        self.queue_ready = False
        self._queue_paths = []
        self._queue_indexes = {}
        self._index_started_at = None
        self._download_started_at = None
        self._downloaded_bytes = 0
        self._byte_rate = 0.0
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        self.status = ttk.Label(body, text="Preparing...", anchor=tk.W)
        self.status.pack(fill=tk.X, pady=(0, 6))
        self.current = ttk.Label(body, text="Current file: -", anchor=tk.W)
        self.current.pack(fill=tk.X, pady=(0, 6))
        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, pady=(0, 8))

        queue_frame = ttk.LabelFrame(body, text="Files remaining")
        self.queue_frame = queue_frame
        queue_frame.pack(fill=tk.BOTH, expand=True)
        self.queue = tk.Listbox(queue_frame, height=10, activestyle="none")
        scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue.yview)
        self.queue.configure(yscrollcommand=scrollbar.set)
        self.queue.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        footer = ttk.Frame(body)
        footer.pack(fill=tk.X, pady=(8, 0))
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side=tk.RIGHT)
        setup_window_dpi(self, base_width=620, base_height=390, min_width=440, min_height=260, parent=parent)
        self.wait_visibility()
        self.grab_set()

    def start_indexing(self, section=""):
        if not self.winfo_exists():
            return
        self.queue.delete(0, tk.END)
        self._queue_paths.clear()
        self._queue_indexes.clear()
        self.queue_frame.config(text=f"Files found in {section}")
        self.current.config(text="Current path: indexing...")
        self.status.config(text=f"Indexing {section}...")
        self._index_started_at = time.monotonic()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

    def add_indexed_paths(self, count, paths, section="", current_path=""):
        if self.winfo_exists():
            for path in paths:
                row = len(self._queue_paths)
                self._queue_paths.append(path)
                self._queue_indexes[path] = row
                self.queue.insert(tk.END, path)
            if current_path:
                self.current.config(text=f"Current path: {current_path}")
                self.queue.yview(tk.END)
            elapsed = max(time.monotonic() - (self._index_started_at or time.monotonic()), 0.001)
            rate = count / elapsed
            self.status.config(
                text=f"Indexing {section}: {count:,} items | {rate:,.1f} items/s | ETA unknown (total not known yet)"
            )

    def set_queue(self, paths, section=""):
        if not self.winfo_exists():
            return
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.queue_frame.config(text="Indexed file queue")
        if self._queue_paths != paths:
            self.queue.delete(0, tk.END)
            self._queue_paths = list(paths)
            self._queue_indexes = {path: index for index, path in enumerate(paths)}
            for path in paths:
                self.queue.insert(tk.END, path)
        self.queue_ready = True
        label = f" for {section}" if section else ""
        self.status.config(text=f"Indexed {len(paths)} files{label}. Starting download...")
        self._download_started_at = time.monotonic()
        self._downloaded_bytes = 0
        self._byte_rate = 0.0
        self.update_idletasks()

    @staticmethod
    def _format_byte_rate(rate):
        value = max(0.0, rate)
        units = ("B/s", "KiB/s", "MiB/s", "GiB/s", "TiB/s")
        unit = 0
        while value >= 1024 and unit < len(units) - 1:
            value /= 1024
            unit += 1
        return f"{value:,.1f} {units[unit]}"

    @staticmethod
    def _download_estimate(done, total, started_at):
        elapsed = max(time.monotonic() - (started_at or time.monotonic()), 0.001)
        rate = done / elapsed
        if rate > 0:
            remaining_seconds = max(0, int((total - done) / rate))
            minutes, seconds = divmod(remaining_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            eta = f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
            return rate, eta
        return rate, "calculating"

    def set_download(self, done, total, path, remaining):
        if not self.winfo_exists():
            return
        active_paths = remaining[1] if isinstance(remaining, tuple) and len(remaining) >= 2 else []
        self.current.config(text=f"Last completed: {path}")
        rate, eta = self._download_estimate(done, total, self._download_started_at)
        if isinstance(remaining, tuple) and len(remaining) == 3:
            self._downloaded_bytes = remaining[2]
        elapsed = max(time.monotonic() - (self._download_started_at or time.monotonic()), 0.001)
        self._byte_rate = self._downloaded_bytes / elapsed
        self.status.config(
            text=f"Downloaded {done:,}/{total:,} items | {rate:,.1f} items/s | "
                 f"{self._format_byte_rate(self._byte_rate)} | ETA {eta}"
        )
        if active_paths:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=(done * 100 / total) if total else 100)
        row = self._queue_indexes.get(path)
        if row is not None:
            self.queue.delete(row)
            self.queue.insert(row, f"Done: {path}")
            self.queue.itemconfig(row, foreground="#777777")

    def set_current_download(self, done, total, path, remaining):
        if not self.winfo_exists():
            return
        active_paths = path.splitlines()
        self.current.config(text=f"Active files ({len(active_paths)}): {', '.join(active_paths)}")
        rate, eta = self._download_estimate(done, total, self._download_started_at)
        self.status.config(
            text=f"Downloaded {done:,}/{total:,} items | {rate:,.1f} items/s | "
                 f"{self._format_byte_rate(self._byte_rate)} | ETA {eta}"
        )
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.queue.selection_clear(0, tk.END)
        for active_path in active_paths:
            row = self._queue_indexes.get(active_path)
            if row is not None:
                self.queue.selection_set(row)
                self.queue.see(row)

    def set_download_rate(self, done, total, path, details):
        if not self.winfo_exists():
            return
        transferred, rate, pending, active = details
        self._downloaded_bytes = transferred
        self._byte_rate = rate
        item_rate, eta = self._download_estimate(done, total, self._download_started_at)
        self.current.config(text=f"Active files: {', '.join(active)}" if active else f"Current file: {path}")
        self.status.config(
            text=f"Downloaded {done:,}/{total:,} items | {item_rate:,.1f} items/s | "
                 f"{self._format_byte_rate(rate)} | {transferred:,} bytes | ETA {eta}"
        )

    def set_failed(self, done, total, path, error):
        if not self.winfo_exists():
            return
        self.current.config(text=f"Failed: {path} — {error}")
        self.status.config(text=f"Downloaded or failed {done:,}/{total:,} items")
        row = self._queue_indexes.get(path)
        if row is not None:
            self.queue.delete(row)
            self.queue.insert(row, f"Failed: {path}")
            self.queue.itemconfig(row, foreground="#a00000")

    def set_archiving(self, done, total, path):
        if not self.winfo_exists():
            return
        self.status.config(text=f"Creating archive: {done} of {total} files")
        self.current.config(text=f"Current file: {path}")
        self.progress.configure(value=(done * 100 / total) if total else 100)

    def finish(self, message, close_after_ms=None):
        if self.winfo_exists():
            self.status.config(text=message)
            self.cancel_button.config(state=tk.DISABLED, text="Close", command=self.destroy)
            if close_after_ms is not None:
                self.after(close_after_ms, lambda: self.destroy() if self.winfo_exists() else None)

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()
        if self.winfo_exists():
            self.status.config(text="Canceling...")
            self.cancel_button.config(state=tk.DISABLED)


class RestoreSelectionDialog(tk.Toplevel):
    """Choose files from a local backup to restore to their device paths."""

    def __init__(self, parent, files):
        super().__init__(parent)
        self.title("Select Files to Restore")
        self.transient(parent)
        self.resizable(True, True)
        self.files = files
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Select backup files to copy to the device:").pack(anchor=tk.W, pady=(0, 6))
        rows = ttk.Frame(body)
        rows.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(rows, selectmode=tk.EXTENDED, activestyle="none", width=90, height=18)
        scrollbar = ttk.Scrollbar(rows, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        for remote_path, _source in files:
            self.listbox.insert(tk.END, remote_path)
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="Select All", command=lambda: self.listbox.select_set(0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Restore Selected", command=self._restore).pack(side=tk.RIGHT, padx=(0, 6))
        setup_window_dpi(self, base_width=720, base_height=440, min_width=560, min_height=320, parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.wait_window()

    def _restore(self):
        indexes = self.listbox.curselection()
        if not indexes:
            return
        self.result = [self.files[index] for index in indexes]
        self.destroy()
