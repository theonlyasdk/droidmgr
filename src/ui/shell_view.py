"""Interactive `adb shell` widget: input line, output pane, history and presets."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from core import ConfigManager

from .shell_session import ShellSessionMixin, _PROMPT_RE, _MAX_PROMPT_LEN
from .shell_presets import (ShellPresetsMixin, MAX_OUTPUT_LINES, MAX_HISTORY)


class ShellView(ShellSessionMixin, ShellPresetsMixin):
    """Interactive ADB shell embedded as a notebook tab."""

    def __init__(self, parent_frame, device_manager, set_status_callback,
                 show_error_callback, require_device_callback):
        self.frame = parent_frame
        self.device_manager = device_manager
        self._set_status = set_status_callback
        self._show_error = show_error_callback
        self._require_device = require_device_callback
        self.config = ConfigManager()

        self.selected_device = None
        self.cwd = None
        self.process = None
        self.reader_thread = None
        self.session_id = 0
        self.run_id = 0
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.displayed_count = 0

        # The device shell may echo the command back after a tty is allocated.
        self._echo_pending = None

        self.history: list[str] = []
        self.history_index = 0

        self.preset_var = tk.StringVar()
        self.command_var = tk.StringVar()

        self._poll_after_id = None

        self._create_widgets()
        self._refresh_presets()
        self._update_controls()
        self._schedule_poll()

    # -- widget construction -------------------------------------------
    def _create_widgets(self):
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="Preset:").pack(side=tk.LEFT, padx=(0, 2))
        self.preset_combo = ttk.Combobox(
            toolbar, textvariable=self.preset_var,
            state='readonly', width=22,
        )
        self.preset_combo.pack(side=tk.LEFT, padx=2)
        self.preset_combo.bind('<<ComboboxSelected>>', self._on_preset_selected)
        self.preset_combo.bind('<Return>', lambda e: self._run_preset())

        self.run_preset_btn = ttk.Button(toolbar, text="Run Preset", command=self._run_preset)
        self.run_preset_btn.pack(side=tk.LEFT, padx=2)
        self.save_preset_btn = ttk.Button(toolbar, text="Save Preset", command=self._save_preset)
        self.save_preset_btn.pack(side=tk.LEFT, padx=2)
        self.delete_preset_btn = ttk.Button(toolbar, text="Delete Preset", command=self._delete_preset)
        self.delete_preset_btn.pack(side=tk.LEFT, padx=2)

        self.export_btn = ttk.Button(toolbar, text="Export...", command=self._export)
        self.export_btn.pack(side=tk.RIGHT, padx=2)
        self.clear_btn = ttk.Button(toolbar, text="Clear", command=self.clear)
        self.clear_btn.pack(side=tk.RIGHT, padx=2)
        self.session_btn = ttk.Button(
            toolbar, text="Connect", width=11, command=self._toggle_session)
        self.session_btn.pack(side=tk.RIGHT, padx=2)

        # Shell output
        out_frame = ttk.LabelFrame(self.frame, text="Shell Output")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.status_label = ttk.Label(out_frame, text="No device selected.", anchor=tk.W)
        self.status_label.pack(fill=tk.X, padx=5, pady=(2, 0))

        text_frame = ttk.Frame(out_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.output_text = tk.Text(
            text_frame, wrap=tk.NONE, font=('Monospace', 9),
            state=tk.DISABLED, background='white',
        )
        yscroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        xscroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.output_text.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        self.output_text.tag_configure('cmd', foreground='#0066cc', font=('Monospace', 9, 'bold'))
        self.output_text.tag_configure('err', foreground='#cc0000')
        self.output_text.tag_configure('sys', foreground='#6e6e6e', font=('Monospace', 9, 'italic'))
        self.output_text.tag_configure('ok', foreground='#009000')

        # Command input
        input_frame = ttk.Frame(self.frame)
        input_frame.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.prompt_label = ttk.Label(
            input_frame, text="adb ~$", font=('Monospace', 9), anchor=tk.W)
        self.prompt_label.pack(side=tk.LEFT, padx=(0, 4))

        self.command_entry = ttk.Entry(
            input_frame, textvariable=self.command_var, font=('Monospace', 9))
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.run_btn = ttk.Button(input_frame, text="Run", width=8, command=self._submit)
        self.run_btn.pack(side=tk.LEFT, padx=2)

        self.command_entry.bind('<Return>', lambda e: self._submit())
        self.command_entry.bind('<Up>', self._history_prev)
        self.command_entry.bind('<Down>', self._history_next)
        self.command_entry.bind('<Escape>', lambda e: self.command_var.set(''))
        self.command_entry.bind('<Control-c>', self._send_interrupt)
        self.command_entry.bind('<Control-d>', self._send_eof)

        ttk.Label(
            self.frame,
            text="Enter run  |  Up/Down history  |  Ctrl+C interrupt  |  Ctrl+D exit",
            anchor=tk.W,
        ).pack(fill=tk.X, padx=5, pady=(0, 5))

    # -- device lifecycle ----------------------------------------------
    def set_device(self, device_id):
        """Point the shell at a device, resetting the session when it changes."""
        if device_id != self.selected_device:
            self._stop_session()
            self.selected_device = device_id
            self.cwd = None
            self._echo_pending = None
            self._clear_view()
        if not device_id:
            self._set_hint("No device selected.")
        else:
            self._set_hint(f"Shell ready on {device_id}. Type a command and press Enter.")
        self._update_prompt()
        self._update_controls()

    def destroy(self):
        self._stop_session()
        if self._poll_after_id is not None:
            try:
                self.frame.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

    def focus_input(self):
        try:
            self.command_entry.focus_set()
        except Exception:
            pass


__all__ = ['ShellView', 'MAX_OUTPUT_LINES', 'MAX_HISTORY']
