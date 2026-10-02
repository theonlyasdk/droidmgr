"""Logcat viewer widget for streaming `adb logcat -v brief` output."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog


# brief format: "<PRIO>/<tag>(<pid>): <message>", e.g. "I/ActivityManager( 1234): Start proc"
_BRIEF_RE = re.compile(r'^([VDIWEFS])/(.+)$')

_LEVEL_ORDER = {'V': 0, 'D': 1, 'I': 2, 'W': 3, 'E': 4, 'F': 5, 'S': 6}

_LEVEL_LABELS = {
    'V': 'Verbose (V)',
    'D': 'Debug (D)',
    'I': 'Info (I)',
    'W': 'Warn (W)',
    'E': 'Error (E)',
}

MAX_BUFFER_LINES = 10000
MAX_RENDER_LINES = 2000


def parse_brief_level(line: str) -> str:
    """Extract the log level letter from a `logcat -v brief` line.

    Returns '' for header lines such as '--------- beginning of main'.
    """
    stripped = line.lstrip()
    if not stripped:
        return ''
    match = _BRIEF_RE.match(stripped)
    if match:
        return match.group(1)
    return ''


def level_passes(line_level: str, min_level: str) -> bool:
    """Check if a line level meets the minimum severity filter."""
    if not line_level:
        return True
    return _LEVEL_ORDER.get(line_level, -1) >= _LEVEL_ORDER.get(min_level, 0)


class LogcatView:
    """Streaming logcat viewer embedded as a notebook tab."""

    def __init__(self, parent_frame, device_manager, set_status_callback,
                 show_error_callback, require_device_callback):
        self.frame = parent_frame
        self.device_manager = device_manager
        self._set_status = set_status_callback
        self._show_error = show_error_callback
        self._require_device = require_device_callback

        self.selected_device = None
        self.process = None
        self.reader_thread = None
        self.queue: queue.Queue = queue.Queue()
        self.running = False
        self.paused = False
        self.autoscroll = tk.BooleanVar(value=True)

        self.level_var = tk.StringVar(value=_LEVEL_LABELS['V'])
        self.search_var = tk.StringVar(value='')

        # (raw_line_without_newline, level)
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.displayed_count = 0
        self._poll_after_id = None

        self._create_widgets()
        self._schedule_poll()

    # -- widget construction -------------------------------------------

    def _create_widgets(self):
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="Level:").pack(side=tk.LEFT, padx=(0, 2))
        self.level_combo = ttk.Combobox(
            toolbar,
            textvariable=self.level_var,
            values=list(_LEVEL_LABELS.values()),
            state='readonly',
            width=12,
        )
        self.level_combo.pack(side=tk.LEFT, padx=2)
        self.level_combo.bind('<<ComboboxSelected>>', lambda e: self._refilter())

        ttk.Label(toolbar, text="Search:").pack(side=tk.LEFT, padx=(8, 2))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=24)
        self.search_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=False)
        self.search_var.trace_add('write', lambda *a: self._on_search_changed())
        self.search_entry.bind('<Escape>', lambda e: self.search_var.set(''))

        self.autoscroll_check = ttk.Checkbutton(
            toolbar, text="Autoscroll", variable=self.autoscroll)
        self.autoscroll_check.pack(side=tk.LEFT, padx=(8, 2))

        # Right-aligned action buttons
        self.export_btn = ttk.Button(toolbar, text="Export...", command=self._export)
        self.export_btn.pack(side=tk.RIGHT, padx=2)

        self.clear_btn = ttk.Button(toolbar, text="Clear", command=self.clear)
        self.clear_btn.pack(side=tk.RIGHT, padx=2)

        self.pause_btn = ttk.Button(
            toolbar, text="Pause", command=self._toggle_pause, width=8)
        self.pause_btn.pack(side=tk.RIGHT, padx=2)

        # Log output
        log_frame = ttk.LabelFrame(self.frame, text="Logcat (brief)")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.status_label = ttk.Label(log_frame, text="No device selected.", anchor=tk.W)
        self.status_label.pack(fill=tk.X, padx=5, pady=(2, 0))

        text_frame = ttk.Frame(log_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text = tk.Text(
            text_frame, wrap=tk.NONE, font=('Monospace', 9),
            state=tk.DISABLED, background='white',
        )
        yscroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        xscroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.log_text.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        self.log_text.tag_configure('V', foreground='#6e6e6e')
        self.log_text.tag_configure('D', foreground='#0066cc')
        self.log_text.tag_configure('I', foreground='#009000')
        self.log_text.tag_configure('W', foreground='#cc7000')
        self.log_text.tag_configure('E', foreground='#cc0000')
        self.log_text.tag_configure('F', foreground='#cc0000', font=('Monospace', 9, 'bold'))

        # Right-click context menu
        self.log_menu = tk.Menu(self.log_text, tearoff=0)
        self.log_menu.add_command(label="Copy", command=self._copy_selection)
        self.log_menu.add_command(label="Copy All", command=self._copy_all)
        self.log_menu.add_command(label="Select All", command=self._select_all)
        self.log_menu.add_separator()
        self.log_menu.add_command(label="Pause", command=self._toggle_pause)
        self._pause_menu_index = self.log_menu.index('end')
        self.log_menu.add_command(label="Export...", command=self._export)
        self.log_menu.add_separator()
        self.log_menu.add_command(label="Clear", command=self.clear)
        self.log_text.bind('<Button-3>', self._show_log_menu)

    # -- device lifecycle ----------------------------------------------

    def set_device(self, device_id, force_refresh=False, autostart=False):
        changed = (self.selected_device != device_id)
        if changed:
            self.stop()
            self.selected_device = device_id
            self._clear_view()
            with self.buffer_lock:
                self.buffer.clear()
            self.displayed_count = 0
        else:
            self.selected_device = device_id
        if not device_id:
            self._set_hint("No device selected.")
            return
        if autostart and (changed or force_refresh) and not self.running:
            self.start()

    def start(self):
        if self.running:
            return
        if not self.selected_device:
            self._set_hint("No device selected.")
            return
        if hasattr(self.device_manager, 'is_device_ready'):
            try:
                if not self.device_manager.is_device_ready(self.selected_device):
                    self._set_hint(
                        f"Device '{self.selected_device}' is not ready. "
                        "Select a device in 'device' state.")
                    return
            except Exception:
                pass
        try:
            self.process = self.device_manager.get_logcat(self.selected_device)
        except Exception as exc:
            self._show_error("Logcat Error", f"Could not start logcat:\n{exc}")
            self._set_hint(f"Could not start logcat: {exc}")
            return
        self.running = True
        self._set_hint(f"Streaming logcat from {self.selected_device} ...")
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()

    def stop(self):
        self.running = False
        proc, self.process = self.process, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Drain stale queued lines from the previous stream
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def destroy(self):
        self.running = False
        if self._poll_after_id is not None:
            try:
                self.frame.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None
        self.stop()

    # -- filtering helpers ----------------------------------------------

    def _current_min_level(self) -> str:
        for letter, label in _LEVEL_LABELS.items():
            if self.level_var.get() == label:
                return letter
        return 'V'

    def _line_visible(self, line: str, level: str) -> bool:
        if not level_passes(level, self._current_min_level()):
            return False
        needle = self.search_var.get().strip().lower()
        if needle and needle not in line.lower():
            return False
        return True

    def _on_search_changed(self):
        # Debounce rapid keystrokes via a short after() delay.
        if getattr(self, '_search_after_id', None):
            try:
                self.frame.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.frame.after(250, self._refilter)

    def _refilter(self):
        self._clear_view()
        with self.buffer_lock:
            snapshot = list(self.buffer[-MAX_RENDER_LINES:])
        for line, level in snapshot:
            if self._line_visible(line, level):
                self._append_line(line, level)
        self._update_status()

    # -- streaming -------------------------------------------------------

    def _read_loop(self):
        proc = self.process
        try:
            while self.running and proc is not None and proc.stdout is not None:
                line = proc.stdout.readline()
                if not line:
                    break
                self.queue.put(line)
        except Exception as exc:
            try:
                self.queue.put(f"E/droidmgr(    0): [logcat reader error: {exc}]\n")
            except Exception:
                pass
        finally:
            if self.running:
                self.queue.put(None)

    def _schedule_poll(self):
        self._poll()

    def _poll(self):
        try:
            lines = []
            while True:
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    if self.running:
                        self.running = False
                        self._set_hint("logcat stream ended (device disconnected?).")
                    continue
                lines.append(item)
            if lines:
                self._handle_new_lines(lines)
        finally:
            try:
                if self.frame.winfo_exists():
                    self._poll_after_id = self.frame.after(100, self._poll)
            except Exception:
                pass

    def _handle_new_lines(self, lines):
        new_visible = []
        with self.buffer_lock:
            for raw in lines:
                line = raw.rstrip('\r\n')
                level = parse_brief_level(line)
                self.buffer.append((line, level))
                if len(self.buffer) > MAX_BUFFER_LINES:
                    del self.buffer[:len(self.buffer) - MAX_BUFFER_LINES]
                if self._line_visible(line, level):
                    new_visible.append((line, level))
        if self.paused:
            self._update_status()
            return
        # Cap a single batch to keep the UI responsive on log bursts.
        if len(new_visible) > MAX_RENDER_LINES:
            self._refilter()
            return
        for line, level in new_visible:
            self._append_line(line, level)
        self._update_status()
        if self.autoscroll.get() and new_visible:
            try:
                self.log_text.see(tk.END)
            except Exception:
                pass

    # -- view helpers -----------------------------------------------------

    def _append_line(self, line: str, level: str):
        try:
            self.log_text.configure(state=tk.NORMAL)
            tag = level if level in ('V', 'D', 'I', 'W', 'E', 'F') else None
            if tag:
                self.log_text.insert(tk.END, line + '\n', tag)
            else:
                self.log_text.insert(tk.END, line + '\n')
            self.displayed_count += 1
            # Trim the widget to bound memory on long streams.
            widget_lines = int(self.log_text.index('end-1c').split('.')[0])
            if widget_lines > MAX_RENDER_LINES + 500:
                self.log_text.delete('1.0', f'{widget_lines - MAX_RENDER_LINES}.0')
                self.displayed_count = MAX_RENDER_LINES
            self.log_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _clear_view(self):
        try:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete('1.0', tk.END)
            self.log_text.configure(state=tk.DISABLED)
        except Exception:
            pass
        self.displayed_count = 0

    def _set_hint(self, message: str):
        try:
            self.status_label.config(text=message)
        except Exception:
            pass
        try:
            self._set_status(message)
        except Exception:
            pass

    def _update_status(self):
        with self.buffer_lock:
            total = len(self.buffer)
        state = "paused" if self.paused else ("streaming" if self.running else "stopped")
        dev = self.selected_device or "no device"
        self._set_hint(
            f"logcat [{dev}] {state} | "
            f"{self.displayed_count} shown / {total} buffered | "
            f"level>={self._current_min_level()}"
        )

    # -- actions -----------------------------------------------------------

    def _toggle_pause(self):
        self.paused = not self.paused
        try:
            self.pause_btn.config(text="Resume" if self.paused else "Pause")
        except Exception:
            pass
        if not self.paused:
            # Re-render so lines buffered while paused become visible.
            self._refilter()
        else:
            self._update_status()

    def _show_log_menu(self, event):
        try:
            self.log_menu.entryconfig(
                self._pause_menu_index,
                label="Resume" if self.paused else "Pause")
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()

    def _copy_selection(self):
        try:
            text = self.log_text.get('sel.first', 'sel.end')
        except tk.TclError:
            self._set_status("No log text selected")
            return
        self._copy_to_clipboard(text)
        count = text.count('\n') + 1
        self._set_status(f"Copied {count} line{'' if count == 1 else 's'} to clipboard")

    def _copy_all(self):
        self._select_all()
        self._copy_selection()

    def _select_all(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.tag_add('sel', '1.0', tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see('1.0')

    def _copy_to_clipboard(self, text):
        self.log_text.clipboard_clear()
        self.log_text.clipboard_append(text)
        # Tk owns the clipboard while the app runs; update() makes it persist
        # after the widget is garbage collected on exit.
        self.log_text.update()

    def clear(self):
        with self.buffer_lock:
            self.buffer.clear()
        self._clear_view()
        device_id = self.selected_device
        if device_id:
            def task():
                try:
                    self.device_manager.clear_logcat(device_id)
                except Exception:
                    pass
            threading.Thread(target=task, daemon=True).start()
        self._set_status("Logcat view cleared")
        self._update_status()

    def _export(self):
        if not self.buffer:
            try:
                self._show_error("Export Logcat", "There are no log lines to export yet.")
            except Exception:
                pass
            return
        path = filedialog.asksaveasfilename(
            title="Export Logcat",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        min_level = self._current_min_level()
        needle = self.search_var.get().strip().lower()
        with self.buffer_lock:
            snapshot = list(self.buffer)
        try:
            with open(path, 'w', encoding='utf-8', errors='replace') as out:
                for line, level in snapshot:
                    if not level_passes(level, min_level):
                        continue
                    if needle and needle not in line.lower():
                        continue
                    out.write(line + '\n')
            self._set_status(f"Exported logcat to {path}")
        except OSError as exc:
            self._show_error("Export Logcat", f"Could not write file:\n{exc}")
