"""Interactive `adb shell` widget: input line, output pane, history and presets."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from core import ConfigManager


MAX_OUTPUT_LINES = 5000
MAX_HISTORY = 500

# Device shell prompt, e.g. "shell:/sdcard $", "toybox:/ #", "$".
_PROMPT_RE = re.compile(r'^(?:[^/\s]*@)?(?P<cwd>/[^\s#$]*)?\s*([#$])\s*$')
_MAX_PROMPT_LEN = 60


class ShellView:
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

    # -- session management --------------------------------------------

    def _session_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _toggle_session(self):
        if self._session_alive():
            self._stop_session()
            self._append_line("[session closed]", 'sys')
        else:
            if self._start_session():
                self._append_line("[type 'exit' or press Ctrl+D to close]", 'sys')

    def _start_session(self) -> bool:
        if self._session_alive():
            return True
        if not self.selected_device:
            self._append_line("[no device selected]", 'err')
            return False
        try:
            self.process = self.device_manager.start_shell_session(self.selected_device)
        except Exception as exc:
            self.process = None
            self._append_line(f"[could not start interactive shell: {exc}]", 'err')
            self._update_controls()
            return False
        self.session_id += 1
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        self._append_line(f"[interactive shell started on {self.selected_device}]", 'sys')
        self._update_controls()
        return True

    def _stop_session(self):
        # Bump the id so a reader thread winding down cannot report this session
        # as having ended unexpectedly.
        self.session_id += 1
        proc, self.process = self.process, None
        if proc is not None:
            for closer in (lambda: proc.stdin.close(), proc.terminate):
                try:
                    closer()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._drain_queue()
        self._update_controls()

    def _send_interrupt(self, event=None):
        if self._session_alive():
            self._append_line("^C", 'sys')
            self._write_session("\x03")
            return 'break'
        return None

    def _send_eof(self, event=None):
        if self._session_alive():
            self._append_line("^D", 'sys')
            self._write_session("\x04")
            return 'break'
        return None

    def _write_session(self, text: str):
        try:
            self.process.stdin.write(text + '\n')
            self.process.stdin.flush()
        except Exception as exc:
            self._append_line(f"[shell input failed: {exc}]", 'err')
            self._stop_session()

    def _read_loop(self):
        proc = self.process
        session = self.session_id
        try:
            while proc is not None and proc.stdout is not None:
                line = proc.stdout.readline()
                if not line:
                    break
                self.queue.put(('line', session, line.rstrip('\r\n')))
        except Exception as exc:
            try:
                self.queue.put(('line', session, f"[shell reader error: {exc}]"))
            except Exception:
                pass
        finally:
            self.queue.put(('exit', session, None))

    # -- command execution ----------------------------------------------

    def _submit(self):
        command = self.command_var.get().strip()
        if not command:
            return
        if not self._require_device():
            return
        self.command_var.set('')
        self._record_history(command)
        self._append_line(f"{self._prompt_text()} {command}", 'cmd')
        if not self._session_alive():
            # Fall back to a single `adb shell <command>` when no session can be
            # established (older adb without `-t`, device in a bad state, ...).
            if not self._start_session():
                self._run_one_shot(command)
                return
        self._echo_pending = command
        self._write_session(command)

    def _run_one_shot(self, command: str):
        """Run a command without an interactive session (fresh `adb shell`)."""
        if self.busy:
            return
        device_id = self.selected_device
        self.run_id += 1
        run_id = self.run_id
        self.busy = True
        self._append_line("[no interactive session - running one-shot]", 'sys')
        self._update_controls()

        def task():
            try:
                result = ('ok', self.device_manager.run_shell_command(device_id, command))
            except Exception as exc:
                result = ('error', str(exc))
            self.queue.put(('result', run_id, result))

        threading.Thread(target=task, daemon=True).start()

    def _handle_result(self, result):
        kind, payload = result
        if kind == 'error':
            self._append_line(payload, 'err')
        else:
            code, stdout, stderr = payload
            for line in (stdout or '').splitlines():
                self._append_line(line, None)
            for line in (stderr or '').splitlines():
                self._append_line(line, 'err')
            self._append_line(f"[exit {code}]", 'ok' if code == 0 else 'err')
        self.busy = False
        self._update_controls()
        self._update_status()

    # -- history ---------------------------------------------------------

    def _record_history(self, command: str):
        if not self.history or self.history[-1] != command:
            self.history.append(command)
            if len(self.history) > MAX_HISTORY:
                del self.history[:len(self.history) - MAX_HISTORY]
        self.history_index = len(self.history)

    def _history_prev(self, event=None):
        if not self.history:
            return 'break'
        if self.history_index > 0:
            self.history_index -= 1
        self.command_var.set(self.history[self.history_index])
        return 'break'

    def _history_next(self, event=None):
        if not self.history:
            return 'break'
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.command_var.set(self.history[self.history_index])
        else:
            self.history_index = len(self.history)
            self.command_var.set('')
        return 'break'

    # -- presets ---------------------------------------------------------

    def _load_presets(self):
        presets = []
        for item in self.config.get('shell', 'presets', []) or []:
            name = str(item.get('name', '')).strip()
            command = str(item.get('command', '')).strip()
            if name and command:
                presets.append({'name': name, 'command': command})
        return presets

    def _refresh_presets(self):
        presets = self._load_presets()
        self.preset_combo.configure(values=[p['name'] for p in presets])
        if self.preset_var.get() not in [p['name'] for p in presets]:
            self.preset_var.set('')

    def _on_preset_selected(self, event=None):
        preset = self._selected_preset()
        if preset:
            self.command_var.set(preset['command'])
        self._update_controls()

    def _selected_preset(self):
        name = self.preset_var.get().strip()
        for preset in self._load_presets():
            if preset['name'] == name:
                return preset
        return None

    def _run_preset(self):
        preset = self._selected_preset()
        if not preset:
            self._show_error("Shell", "Select a preset first, or save the current command as one.")
            return
        self.command_var.set(preset['command'])
        self._submit()

    def _save_preset(self):
        command = self.command_var.get().strip()
        if not command:
            self._show_error("Save Preset", "Type the command to save in the input box first.")
            return
        name = simpledialog.askstring(
            "Save Preset", "Preset name:", parent=self.frame,
            initialvalue=self.preset_var.get().strip())
        if not name or not name.strip():
            return
        name = name.strip()
        presets = self._load_presets()
        existing = next((p for p in presets if p['name'] == name), None)
        if existing:
            if not messagebox.askyesno(
                    "Save Preset", f"Replace the existing preset '{name}'?", parent=self.frame):
                return
            existing['command'] = command
        else:
            presets.append({'name': name, 'command': command})
        self.config.set('shell', 'presets', presets)
        self._refresh_presets()
        self.preset_var.set(name)
        self._set_status(f"Saved shell preset '{name}'")

    def _delete_preset(self):
        name = self.preset_var.get().strip()
        if not name:
            self._show_error("Delete Preset", "Select the preset to delete first.")
            return
        if not messagebox.askyesno(
                "Delete Preset", f"Delete preset '{name}'?", parent=self.frame):
            return
        presets = [p for p in self._load_presets() if p['name'] != name]
        self.config.set('shell', 'presets', presets)
        self._refresh_presets()
        self._set_status(f"Deleted shell preset '{name}'")

    # -- output pane -----------------------------------------------------

    def clear(self):
        self._clear_view()
        self._set_status("Shell output cleared")
        self._update_status()

    def _export(self):
        if not self.output_text.get('1.0', tk.END).strip():
            self._show_error("Export Shell Output", "There is no shell output to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export Shell Output",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8', errors='replace') as out:
                out.write(self.output_text.get('1.0', tk.END))
            self._set_status(f"Exported shell output to {path}")
        except OSError as exc:
            self._show_error("Export Shell Output", f"Could not write file:\n{exc}")

    def _append_line(self, line: str, tag=None):
        try:
            self.output_text.configure(state=tk.NORMAL)
            if tag:
                self.output_text.insert(tk.END, line + '\n', tag)
            else:
                self.output_text.insert(tk.END, line + '\n')
            self.displayed_count += 1
            # Trim the widget to bound memory on long sessions.
            widget_lines = int(self.output_text.index('end-1c').split('.')[0])
            if widget_lines > MAX_OUTPUT_LINES + 500:
                self.output_text.delete('1.0', f'{widget_lines - MAX_OUTPUT_LINES}.0')
                self.displayed_count = MAX_OUTPUT_LINES
            self.output_text.configure(state=tk.DISABLED)
            self.output_text.see(tk.END)
        except Exception:
            pass

    def _clear_view(self):
        try:
            self.output_text.configure(state=tk.NORMAL)
            self.output_text.delete('1.0', tk.END)
            self.output_text.configure(state=tk.DISABLED)
        except Exception:
            pass
        self.displayed_count = 0

    # -- polling ----------------------------------------------------------

    def _schedule_poll(self):
        self._poll()

    def _poll(self):
        try:
            while True:
                try:
                    kind, token, payload = self.queue.get_nowait()
                except queue.Empty:
                    break
                # Ignore anything left over from a session or run we replaced.
                if kind == 'result':
                    if token != self.run_id:
                        continue
                elif token != self.session_id:
                    continue
                if kind == 'line':
                    self._handle_line(payload)
                elif kind == 'exit':
                    self._handle_exit()
                elif kind == 'result':
                    self._handle_result(payload)
        finally:
            try:
                if self.frame.winfo_exists():
                    self._poll_after_id = self.frame.after(100, self._poll)
            except Exception:
                pass

    def _drain_queue(self):
        """Drop stale session output, keeping any in-flight one-shot result."""
        try:
            while True:
                kind, token, payload = self.queue.get_nowait()
                if kind == 'result':
                    self.queue.put((kind, token, payload))
        except queue.Empty:
            pass

    def _handle_line(self, line: str):
        if self._is_prompt(line):
            return
        if self._echo_pending is not None:
            if line.strip() == self._echo_pending.strip():
                self._echo_pending = None
                return
            self._echo_pending = None
        self._append_line(line, None)
        self._update_status()

    def _handle_exit(self):
        if not self._session_alive():
            self._append_line("[session ended]", 'sys')
        self.process = None
        self._echo_pending = None
        self._update_controls()
        self._update_status()

    def _is_prompt(self, line: str) -> bool:
        stripped = line.rstrip()
        if not stripped or len(stripped) > _MAX_PROMPT_LEN:
            return False
        match = _PROMPT_RE.match(stripped)
        if not match:
            return False
        self.cwd = match.group('cwd') or self.cwd
        self._update_prompt()
        return True

    def _prompt_text(self) -> str:
        return f"{self.selected_device or 'adb'} {self.cwd or '~'}$"

    def _update_prompt(self):
        try:
            self.prompt_label.config(text=self._prompt_text())
        except Exception:
            pass

    # -- state ------------------------------------------------------------

    def _update_controls(self):
        alive = self._session_alive()
        has_device = self.selected_device is not None
        try:
            self.session_btn.config(
                text="Disconnect" if alive else "Connect",
                state=tk.NORMAL if (alive or has_device) else tk.DISABLED)
            self.run_btn.config(
                state=tk.NORMAL if (has_device and not self.busy) else tk.DISABLED)
            self.command_entry.config(
                state=tk.NORMAL if has_device else tk.DISABLED)
            has_preset = bool(self.preset_var.get().strip())
            preset_state = tk.NORMAL if (has_device and has_preset) else tk.DISABLED
            self.run_preset_btn.config(state=preset_state)
            self.save_preset_btn.config(
                state=tk.NORMAL if has_device else tk.DISABLED)
            self.delete_preset_btn.config(state=preset_state)
        except Exception:
            pass

    def _update_status(self):
        if not self.selected_device:
            self.status_label.config(text="No device selected.")
            return
        state = "connected" if self._session_alive() else "one-shot"
        if self.busy:
            state = "running"
        self.status_label.config(
            text=f"shell [{self.selected_device}] {state} | "
                 f"cwd {self.cwd or 'unknown'} | {self.displayed_count} lines")

    def _set_hint(self, message: str):
        try:
            self.status_label.config(text=message)
        except Exception:
            pass
        try:
            self._set_status(message)
        except Exception:
            pass
