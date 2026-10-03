"""Logcat viewer widget for streaming `adb logcat -v brief` output."""

from collections import deque
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog

from .logcat_filter import (
    MAX_BUFFER_LINES, MAX_RENDER_LINES, _LEVEL_LABELS,
    parse_brief_level, level_passes, LogcatFilterMixin,
)
from .logcat_stream import LogcatStreamMixin


class LogcatView(LogcatStreamMixin, LogcatFilterMixin):
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
        self._session_id = 0
        self.queue: queue.Queue = queue.Queue(maxsize=2000)
        self.running = False
        self.paused = False
        self.autoscroll = tk.BooleanVar(value=True)

        self.level_var = tk.StringVar(value=_LEVEL_LABELS['V'])
        self.search_var = tk.StringVar(value='')

        # (raw_line_without_newline, level)
        self.buffer = deque(maxlen=MAX_BUFFER_LINES)
        self.buffer_lock = threading.Lock()
        self.displayed_count = 0
        self._poll_after_id = None
        self._search_after_id = None

        self._create_widgets()

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

    # -- view helpers -----------------------------------------------------
    def _append_lines_batch(self, lines_to_add: list):
        if not lines_to_add:
            return
        try:
            self.log_text.configure(state=tk.NORMAL)
            for line, level in lines_to_add:
                tag = level if level in ('V', 'D', 'I', 'W', 'E', 'F') else None
                if tag:
                    self.log_text.insert(tk.END, line + '\n', tag)
                else:
                    self.log_text.insert(tk.END, line + '\n')

            # Trim the widget to bound memory on long streams.
            widget_lines = int(self.log_text.index('end-1c').split('.')[0])
            if widget_lines > MAX_RENDER_LINES + 500:
                delete_count = widget_lines - MAX_RENDER_LINES
                self.log_text.delete('1.0', f'{delete_count + 1}.0')
                self.displayed_count = MAX_RENDER_LINES
            else:
                self.displayed_count = widget_lines
        except Exception:
            pass
        finally:
            try:
                self.log_text.configure(state=tk.DISABLED)
            except Exception:
                pass

    def _clear_view(self):
        try:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete('1.0', tk.END)
        except Exception:
            pass
        finally:
            try:
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


__all__ = ['LogcatView', 'parse_brief_level', 'level_passes',
           'MAX_BUFFER_LINES', 'MAX_RENDER_LINES']
