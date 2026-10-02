"""One-click screenshot and screen recording, independent of scrcpy mirroring."""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import ConfigManager
from core.config_manager import MAX_RECORD_SECONDS
from .dpi import setup_window_dpi


BIT_RATE_CHOICES = ['', '2M', '4M', '8M', '16M', '32M']
BIT_RATE_LABELS = {'': 'Device default', '2M': '2 Mbps (low)', '4M': '4 Mbps', '8M': '8 Mbps',
                   '16M': '16 Mbps', '32M': '32 Mbps (high)'}
SIZE_CHOICES = ['', '1280x720', '1920x1080']


def open_path(path) -> bool:
    """Open a file with the OS default application. Returns False if that failed."""
    path = str(path)
    try:
        if os.name == 'nt':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        return False


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def _default_dir(kind: str) -> Path:
    if kind == 'screenshot':
        folder = 'Pictures'
    elif kind == 'record':
        folder = 'Videos'
    else:
        folder = 'Downloads'
    return Path.home() / folder / 'droidmgr'


def _existing_dir(configured: str, fallback: Path) -> str:
    for candidate in (configured, str(fallback)):
        if candidate and Path(candidate).is_dir():
            return candidate
    return str(Path.home())


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


# -- screenshot ------------------------------------------------------------


def remember_folder(root, config, key, label, saved_path, set_status, show_info,
                    note: str = '') -> None:
    """Announce a saved file and offer to remember its folder as the default.

    `key` is the `capture` config key holding the remembered folder, so each
    feature keeps its own default: screenshot_dir, record_dir, apk_dir.
    `note` is appended to the dialog when there is something extra to say.
    """
    saved_path = str(saved_path)
    folder = str(Path(saved_path).parent)
    set_status(f"{label} saved to {saved_path}")
    if str(config.get('capture', key, '')) == folder:
        show_info(f"{label} saved to:\n{saved_path}{note}")
        return
    if messagebox.askyesno(
            f"{label} Saved",
            f"Saved to:\n{saved_path}\n\nRemember '{folder}' as the default "
            f"{label.lower()} folder?{note}",
            parent=root):
        config.set('capture', key, folder)


def take_screenshot(root, device_manager, device_id, set_status, show_error, show_info) -> None:
    """Ask where to save a PNG capture, write it, then offer to remember the folder."""
    config = ConfigManager()
    path = filedialog.asksaveasfilename(
        parent=root,
        title="Save Screenshot",
        initialdir=_existing_dir(config.get('capture', 'screenshot_dir', ''),
                                 _default_dir('screenshot')),
        initialfile=f"screenshot-{_timestamp()}.png",
        defaultextension=".png",
        filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
    )
    if not path:
        return

    set_status("Capturing screenshot...")

    def task():
        try:
            data = device_manager.capture_screenshot(device_id)
        except Exception as exc:
            message = str(exc)
            root.after(0, lambda: show_error("Screenshot Error", message))
            return
        try:
            Path(path).write_bytes(data)
        except OSError as exc:
            message = f"Could not write the file:\n{exc}"
            root.after(0, lambda: show_error("Screenshot Error", message))
            return
        root.after(0, lambda: _on_screenshot_saved(root, path, config, set_status, show_info))

    threading.Thread(target=task, daemon=True).start()


def _on_screenshot_saved(root, path, config, set_status, show_info) -> None:
    remember_folder(root, config, 'screenshot_dir', 'Screenshot', path, set_status, show_info)


# -- screen recording ------------------------------------------------------


class ScreenRecordDialog(tk.Toplevel):
    """Parameter dialog for a device-side `screenrecord` run."""

    def __init__(self, parent, device_id):
        super().__init__(parent)
        self.title("Record Screen")
        self.transient(parent)
        self.device_id = device_id
        self.config = ConfigManager()
        self.result = None

        self.geometry("540x360")
        self.resizable(True, False)

        container = ttk.Frame(self, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text=f"Records '{device_id}' with adb shell screenrecord.\n"
                 "This is independent of screen mirroring, so it works while scrcpy is off.\n"
                 "The video is recorded to /sdcard first, then pulled, removed and opened.",
            wraplength=480, justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))

        row = 1
        ttk.Label(container, text="Duration (seconds):").grid(row=row, column=0, sticky='w', pady=4)
        config_limit = self.config.get('capture', 'record_time_limit', 30)
        self.time_limit_var = tk.StringVar(value=str(config_limit))
        ttk.Spinbox(container, from_=1, to=MAX_RECORD_SECONDS, width=8,
                    textvariable=self.time_limit_var).grid(row=row, column=1, sticky='w', pady=4, padx=5)
        ttk.Label(container, text=f"1 - {MAX_RECORD_SECONDS} seconds (device limit)").grid(
            row=row, column=2, sticky='w', pady=4)
        row += 1

        ttk.Label(container, text="Video bit rate:").grid(row=row, column=0, sticky='w', pady=4)
        stored_rate = self.config.get('capture', 'record_bit_rate', '') or ''
        self.bit_rate_var = tk.StringVar(value=BIT_RATE_LABELS.get(stored_rate, stored_rate))
        self.bit_rate_cb = ttk.Combobox(
            container, textvariable=self.bit_rate_var, state='readonly',
            values=[BIT_RATE_LABELS[r] for r in BIT_RATE_CHOICES])
        self.bit_rate_cb.grid(row=row, column=1, sticky='ew', pady=4, padx=5)
        row += 1

        ttk.Label(container, text="Size limit:").grid(row=row, column=0, sticky='w', pady=4)
        self.size_var = tk.StringVar(value=self.config.get('capture', 'record_size', '') or '')
        ttk.Combobox(container, textvariable=self.size_var, values=SIZE_CHOICES).grid(
            row=row, column=1, sticky='ew', pady=4, padx=5)
        ttk.Label(container, text="width x height, blank = device default").grid(
            row=row, column=2, sticky='w', pady=4)
        row += 1

        ttk.Label(container, text="Save recording to:").grid(row=row, column=0, sticky='w', pady=4)
        path_frame = ttk.Frame(container)
        path_frame.grid(row=row, column=1, sticky='ew', pady=4, padx=5)
        path_frame.columnconfigure(0, weight=1)
        self.record_dir_var = tk.StringVar(
            value=_existing_dir(self.config.get('capture', 'record_dir', ''),
                                _default_dir('record')))
        ttk.Entry(path_frame, textvariable=self.record_dir_var).grid(row=0, column=0, sticky='ew')
        ttk.Button(path_frame, text="Browse...", width=10,
                   command=self._browse_record_dir).grid(row=0, column=1, padx=(5, 0))
        row += 1

        # The container is laid out with grid, so the button row has to use grid too.
        # The empty row above it soaks up the spare height and keeps the buttons low.
        container.rowconfigure(row, weight=1)
        btn_frame = ttk.Frame(container, padding=(0, 10, 0, 0))
        btn_frame.grid(row=row + 1, column=0, columnspan=3, sticky='ew')
        ttk.Button(btn_frame, text="Start Recording", command=self._on_start).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        setup_window_dpi(self, base_width=540, base_height=360, min_width=480, min_height=340,
                         parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())

    def _browse_record_dir(self):
        folder = filedialog.askdirectory(
            parent=self, title="Select folder for the recording",
            initialdir=self.record_dir_var.get())
        if folder:
            self.record_dir_var.set(folder)

    def _on_start(self):
        try:
            time_limit = int(str(self.time_limit_var.get()).strip())
        except ValueError:
            time_limit = 0
        if not 1 <= time_limit <= MAX_RECORD_SECONDS:
            messagebox.showerror(
                "Invalid Duration",
                f"Enter a duration between 1 and {MAX_RECORD_SECONDS} seconds.",
                parent=self)
            return

        label = self.bit_rate_var.get()
        bit_rate = next((r for r, l in BIT_RATE_LABELS.items() if l == label), label.strip())

        folder = self.record_dir_var.get().strip()
        if not folder:
            messagebox.showerror("Invalid Folder", "Choose a folder for the recording.", parent=self)
            return

        # Remember the parameters for next time.
        self.config.set('capture', 'record_dir', folder)
        self.config.set('capture', 'record_time_limit', time_limit)
        self.config.set('capture', 'record_bit_rate', bit_rate)
        self.config.set('capture', 'record_size', self.size_var.get().strip())

        self.result = {
            'time_limit': time_limit,
            'bit_rate': bit_rate,
            'size': self.size_var.get().strip(),
            'directory': folder,
        }
        self.destroy()


class ScreenRecordProgressDialog(tk.Toplevel):
    """Countdown and early-stop control while screenrecord runs on the device."""

    def __init__(self, parent, device_id, total_seconds, on_done, on_error):
        super().__init__(parent)
        self.title("Recording")
        self.transient(parent)
        self.device_id = device_id
        self.total_seconds = total_seconds
        self.on_done = on_done
        self.on_error = on_error

        self.queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.running = True
        self.open_when_done = tk.BooleanVar(value=True)

        self.geometry("560x320")
        self.resizable(True, True)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = ttk.Label(frame, text=f"Recording {device_id}...", font=('', 11, 'bold'))
        self.status_label.pack(anchor=tk.W)

        self.progress = ttk.Progressbar(frame, mode='determinate', maximum=total_seconds)
        self.progress.pack(fill=tk.X, pady=(8, 4))

        self.detail_label = ttk.Label(frame, text=f"0:00 / {_format_duration(total_seconds)}")
        self.detail_label.pack(anchor=tk.W)

        ttk.Checkbutton(
            frame, text="Open the recording when it finishes",
            variable=self.open_when_done).pack(anchor=tk.W, pady=(10, 4))

        self.log_text = tk.Text(frame, wrap=tk.WORD, height=8, font=('Monospace', 9), state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=4)
        scrollbar = ttk.Scrollbar(self.log_text, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        self.stop_btn = ttk.Button(btn_frame, text="Stop and Save", command=self._on_stop)
        self.stop_btn.pack(side=tk.RIGHT)

        setup_window_dpi(self, base_width=560, base_height=320, min_width=460, min_height=280,
                         parent=parent)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._poll()

    # -- controls ---------------------------------------------------------

    def _on_stop(self):
        self.stop_event.set()
        self.status_label.config(text="Stopping, waiting for the device to finish the file...")
        self.stop_btn.config(state=tk.DISABLED)

    def _on_closing(self):
        if not self.running:
            self.close()
            return
        if messagebox.askyesno(
                "Recording in progress",
                "Stop the recording and save it?",
                parent=self):
            self._on_stop()

    def close(self):
        self.running = False
        self.destroy()

    # -- polling ----------------------------------------------------------

    def _poll(self):
        try:
            while True:
                try:
                    kind, payload = self.queue.get_nowait()
                except queue.Empty:
                    break
                if kind == 'tick':
                    self._show_tick(payload)
                elif kind == 'log':
                    self._append_log(payload)
                elif kind == 'done':
                    self.running = False
                    self.close()
                    self.on_done(payload)
                    return
                elif kind == 'error':
                    self.running = False
                    self.close()
                    self.on_error(payload)
                    return
        finally:
            if self.running:
                try:
                    self.after(150, self._poll)
                except Exception:
                    pass

    def _show_tick(self, remaining: float):
        remaining = max(0.0, float(remaining))
        done = max(0.0, self.total_seconds - remaining)
        try:
            self.progress['value'] = done
            self.detail_label.config(
                text=f"{_format_duration(done)} / {_format_duration(self.total_seconds)} elapsed"
                     f"   -   {_format_duration(remaining)} left")
            if self.stop_event.is_set():
                self.status_label.config(text="Stopping...")
        except Exception:
            pass

    def _append_log(self, message: str):
        try:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + '\n')
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        except Exception:
            pass


def record_screen(root, device_manager, device_id, set_status, show_error, show_info) -> None:
    """Show the parameter dialog, record, pull the file and open it."""
    dialog = ScreenRecordDialog(root, device_id)
    root.wait_window(dialog)
    if not dialog.result:
        return

    options = dialog.result
    stamp = _timestamp()
    remote_path = f"/sdcard/droidmgr-recording-{stamp}.mp4"

    def on_done(local_path):
        set_status(f"Recording saved to {local_path}")
        if progress.open_when_done.get() and open_path(local_path):
            return
        show_info(f"Recording saved to:\n{local_path}")

    def on_error(message):
        show_error("Screen Recording Error", message)

    progress = ScreenRecordProgressDialog(
        root, device_id, options['time_limit'], on_done, on_error)
    set_status(f"Recording {device_id}...")

    def task():
        try:
            Path(options['directory']).mkdir(parents=True, exist_ok=True)
            local_path = _unique_path(Path(options['directory']), f"recording-{stamp}", ".mp4")
            process = device_manager.start_screenrecord(
                device_id, remote_path, options['time_limit'],
                options['bit_rate'], options['size'])
        except Exception as exc:
            progress.queue.put(('error', str(exc)))
            return

        started = time.monotonic()
        signalled = False
        while process.poll() is None:
            if progress.stop_event.is_set() and not signalled:
                signalled = True
                try:
                    delivered = device_manager.stop_screenrecord(device_id)
                except Exception:
                    delivered = False
                if not delivered:
                    progress.queue.put((
                        'log',
                        "Could not signal the device to stop early; "
                        "waiting for the time limit instead."))
            progress.queue.put(('tick', options['time_limit'] - (time.monotonic() - started)))
            time.sleep(0.3)

        elapsed = time.monotonic() - started
        progress.queue.put(('log', f"screenrecord exited (code {process.returncode}) "
                                   f"after {elapsed:.1f}s"))
        try:
            output = process.stdout.read() or ''
        except Exception:
            output = ''
        for line in output.splitlines():
            progress.queue.put(('log', line))
        details = '\n'.join(line for line in output.splitlines() if line.strip())[:500]

        try:
            device_manager.download_file(device_id, remote_path, str(local_path))
        except Exception as exc:
            message = (f"The recording could not be pulled from the device:\n{exc}\n\n"
                       f"A partial file may still be on {device_id} at {remote_path}.")
            if details:
                message += f"\n\nDevice output:\n{details}"
            progress.queue.put(('error', message))
            return
        try:
            device_manager.delete_file(device_id, remote_path)
        except Exception:
            pass
        progress.queue.put(('done', str(local_path)))

    threading.Thread(target=task, daemon=True).start()
