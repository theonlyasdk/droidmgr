"""Console tab: one-shot `adb shell <command>` runs on the selected device."""

import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core import AuditLogger, ConfigManager

MAX_HISTORY = 25
# Cap what is collected and displayed; huge dumps are trimmed to the last chunk.
MAX_OUTPUT_BYTES = 200 * 1024
COMMAND_TIMEOUT = 60

CONSOLE_SHORTCUTS = [
    'dumpsys battery',
    'svc wifi enable',
    'svc wifi disable',
    'svc data enable',
    'svc data disable',
]

EMPTY_HINT = 'Type a command and press Enter...'


class ConsoleView:
    """One-shot ADB console embedded as a notebook tab."""

    def __init__(self, parent_frame, device_manager, get_device_callback,
                 set_status_callback, show_error_callback, require_device_callback):
        self.frame = parent_frame
        self.device_manager = device_manager
        self._get_device = get_device_callback
        self._set_status = set_status_callback
        self._show_error = show_error_callback
        self._require_device = require_device_callback
        self.config = ConfigManager()

        self.history = self._load_history()
        self._busy = False
        self._empty = True

        self.command_var = tk.StringVar()
        self.history_var = tk.StringVar()

        self._create_widgets()
        self._show_empty_hint()

    # -- widget construction -------------------------------------------
    def _create_widgets(self):
        # Command toolbar: entry, history and Run
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="Command:").pack(side=tk.LEFT, padx=(0, 4))
        self.command_entry = ttk.Entry(
            toolbar, textvariable=self.command_var, font=('Consolas', 9))
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.command_entry.bind('<Return>', self._on_entry_return)

        self.history_combo = ttk.Combobox(
            toolbar, textvariable=self.history_var,
            state='readonly', width=26, values=list(self.history))
        self.history_combo.pack(side=tk.LEFT, padx=2)
        self.history_combo.bind(
            '<<ComboboxSelected>>', lambda e: self._select_history())

        self.run_btn = ttk.Button(toolbar, text="Run", width=8, command=self._run_current)
        self.run_btn.pack(side=tk.LEFT, padx=2)

        # Shortcut one-liners; each goes through the same confirm flow
        shortcuts = ttk.Frame(self.frame)
        shortcuts.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Label(shortcuts, text="Shortcuts:").pack(side=tk.LEFT, padx=(0, 4))
        for one_liner in CONSOLE_SHORTCUTS:
            ttk.Button(
                shortcuts, text=one_liner,
                command=lambda c=one_liner: self._run_shortcut(c),
            ).pack(side=tk.LEFT, padx=2)

        # Output pane
        out_frame = ttk.LabelFrame(self.frame, text="Console Output")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        btn_bar = ttk.Frame(out_frame)
        btn_bar.pack(fill=tk.X, padx=5, pady=(4, 0))
        self.copy_btn = ttk.Button(btn_bar, text="Copy", width=8, command=self.copy_output)
        self.copy_btn.pack(side=tk.LEFT, padx=2)
        self.clear_btn = ttk.Button(btn_bar, text="Clear", width=8, command=self.clear_output)
        self.clear_btn.pack(side=tk.LEFT, padx=2)

        text_frame = ttk.Frame(out_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.output_text = tk.Text(
            text_frame, wrap=tk.NONE, font=('Consolas', 9),
            state=tk.DISABLED, background='white')
        yscroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        xscroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.output_text.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        self.output_text.tag_configure(
            'hint', foreground='#6e6e6e', font=('Consolas', 9, 'italic'))
        self.output_text.tag_configure(
            'header', foreground='#0066cc', font=('Consolas', 9, 'bold'))
        self.output_text.tag_configure('err', foreground='#cc0000')
        self.output_text.tag_configure(
            'note', foreground='#6e6e6e', font=('Consolas', 9, 'italic'))

    # -- history ---------------------------------------------------------
    def _load_history(self):
        try:
            data = self.config.get('console', 'history', [])
            return [str(c) for c in data if str(c).strip()][:MAX_HISTORY]
        except Exception:
            return []

    def _remember_command(self, command):
        try:
            self.history.remove(command)
        except ValueError:
            pass
        self.history.insert(0, command)
        del self.history[MAX_HISTORY:]
        self.history_combo.config(values=list(self.history))
        self.history_var.set('')
        try:
            self.config.set('console', 'history', list(self.history))
        except Exception:
            pass

    def _select_history(self):
        command = self.history_var.get().strip()
        if command:
            self.command_var.set(command)
            self.command_entry.focus_set()

    # -- running ---------------------------------------------------------
    def _on_entry_return(self, event=None):
        self._run_current()
        return 'break'

    def _run_shortcut(self, command):
        """Fill the entry with a one-liner and go through the normal run flow."""
        self.command_var.set(command)
        self._run_current()

    def _run_current(self):
        command = self.command_var.get().strip()
        if not command:
            self._set_status("Console: type a command first.")
            return
        if self._busy:
            self._set_status("Console: a command is still running.")
            return
        if not self._require_device():
            return
        device = self._get_device()
        if not device:
            return  # the device guard already refused

        if not messagebox.askyesno(
                "Confirm Console Command",
                f"Device: {device}\n\nRun command:\n    {command}",
                parent=self.frame, default='no'):
            self._set_status(f"Console: cancelled '{command}'.")
            return

        AuditLogger.log(device, "CONSOLE_COMMAND", command)
        self._remember_command(command)

        self._busy = True
        self.run_btn.config(state=tk.DISABLED)
        self._set_status(f"Running '{command}'...")
        threading.Thread(
            target=self._worker, args=(device, command), daemon=True).start()

    def _worker(self, device, command):
        result = None
        error = None
        try:
            result = self.device_manager.run_shell_command(
                device, command, timeout=COMMAND_TIMEOUT)
        except Exception as exc:
            error = exc
        else:
            # Trim huge outputs here, on the worker thread, so the UI thread
            # never has to handle a multi-megabyte string.
            returncode, stdout, stderr = result
            result = (returncode, self._cap(stdout), self._cap(stderr))
        self._call_after(self._on_finished, command, result, error)

    def _call_after(self, func, *args):
        try:
            self.frame.after(0, func, *args)
        except Exception:
            pass

    @staticmethod
    def _cap(text):
        """Keep only the last MAX_OUTPUT_BYTES of text, with a truncation marker."""
        if not text:
            return text
        data = text.encode('utf-8', errors='replace')
        if len(data) <= MAX_OUTPUT_BYTES:
            return text
        kept = data[-MAX_OUTPUT_BYTES:]
        return "(output truncated)\n" + kept.decode('utf-8', errors='replace')

    def _on_finished(self, command, result, error):
        self._busy = False
        self.run_btn.config(state=tk.NORMAL)
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        if error is not None:
            self._append('header', f"--- {command} @ {timestamp} ---\n")
            self._append('err', f"error: {error}\n")
            self._show_error("Console Error", str(error))
            self._set_status(f"Console: '{command}' failed.")
            return
        returncode, stdout, stderr = result
        self._append('header', f"--- {command} @ {timestamp} ---\n")
        if stdout:
            self._append(None, stdout + '\n')
        if stderr:
            self._append('err', stderr + '\n')
        if returncode != 0:
            self._append('note', f"[exit code {returncode}]\n")
        self._set_status(f"Console: '{command}' finished (exit {returncode}).")

    # -- output pane ------------------------------------------------------
    def _show_empty_hint(self):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete('1.0', tk.END)
        self.output_text.insert(tk.END, EMPTY_HINT, 'hint')
        self.output_text.config(state=tk.DISABLED)
        self._empty = True

    def _append(self, tag, text):
        try:
            self.output_text.config(state=tk.NORMAL)
            if self._empty:
                self.output_text.delete('1.0', tk.END)
                self._empty = False
            if tag:
                self.output_text.insert(tk.END, text, tag)
            else:
                self.output_text.insert(tk.END, text)
            self.output_text.see(tk.END)
        finally:
            self.output_text.config(state=tk.DISABLED)

    def copy_output(self):
        if self._empty:
            return
        text = self.output_text.get('1.0', tk.END)
        self.frame.clipboard_clear()
        self.frame.clipboard_append(text)
        self._set_status("Console: output copied to clipboard.")

    def clear_output(self):
        self._show_empty_hint()
        self._set_status("Console: output cleared.")

    # -- lifecycle ---------------------------------------------------------
    def destroy(self):
        # The worker thread is a daemon and only reschedules via after(),
        # which fails silently once the widget tree is gone.
        self._busy = False
