"""Interactive shell session lifecycle: pty process, I/O loop, polling."""
"""Split from shell_view.py (MOVE-ONLY); ShellView mixes this in."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from core import ConfigManager

# Device shell prompt, e.g. "shell:/sdcard $", "toybox:/ #", "$".
_PROMPT_RE = re.compile(r'^(?:[^/\s]*@)?(?P<cwd>/[^\s#$]*)?\s*([#$])\s*$')

_MAX_PROMPT_LEN = 60


class ShellSessionMixin:
    """Shell session lifecycle and command execution."""

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
