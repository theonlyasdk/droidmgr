"""Logcat streaming: device process, reader thread and poll loop."""
"""Split from logcat_view.py (MOVE-ONLY); LogcatView mixes this in."""

from collections import deque
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from .logcat_filter import (
    MAX_RENDER_LINES, parse_brief_level, level_passes,
)


class LogcatStreamMixin:
    """Logcat streaming from the device."""

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

        # Thoroughly stop any stale session/process first
        self.stop()

        try:
            self.process = self.device_manager.get_logcat(self.selected_device)
        except Exception as exc:
            self._show_error("Logcat Error", f"Could not start logcat:\n{exc}")
            self._set_hint(f"Could not start logcat: {exc}")
            return

        self._session_id += 1
        current_session = self._session_id
        self.running = True
        self._set_hint(f"Streaming logcat from {self.selected_device} ...")

        self.reader_thread = threading.Thread(
            target=self._read_loop,
            args=(current_session, self.process),
            daemon=True
        )
        self.reader_thread.start()
        self._schedule_poll()

    def stop(self):
        self._session_id += 1
        self.running = False
        if self._poll_after_id is not None:
            try:
                self.frame.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

        proc, self.process = self.process, None
        reader, self.reader_thread = self.reader_thread, None

        if proc is not None or reader is not None:
            def _cleanup_bg(p, r):
                if p is not None:
                    try:
                        if p.stdout:
                            p.stdout.close()
                    except Exception:
                        pass
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    try:
                        p.wait(timeout=0.5)
                    except Exception:
                        try:
                            p.kill()
                        except Exception:
                            pass
                if r is not None and r.is_alive() and threading.current_thread() != r:
                    try:
                        r.join(timeout=0.5)
                    except Exception:
                        pass

            threading.Thread(target=_cleanup_bg, args=(proc, reader), daemon=True).start()

        # Drain stale queued lines from previous session
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def destroy(self):
        if getattr(self, '_search_after_id', None):
            try:
                self.frame.after_cancel(self._search_after_id)
            except Exception:
                pass
            self._search_after_id = None
        self.stop()

    # -- streaming -------------------------------------------------------
    def _read_loop(self, session_id: int, proc):
        try:
            while self.running and self._session_id == session_id and proc is not None and proc.stdout is not None:
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    self.queue.put((session_id, 'line', line), timeout=0.1)
                except queue.Full:
                    pass
        except Exception as exc:
            if self.running and self._session_id == session_id:
                try:
                    self.queue.put(
                        (session_id, 'line', f"E/droidmgr(    0): [logcat reader error: {exc}]\n"),
                        timeout=0.1
                    )
                except Exception:
                    pass
        finally:
            try:
                if proc is not None and proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            if self.running and self._session_id == session_id:
                try:
                    self.queue.put((session_id, 'exit', None), timeout=0.1)
                except Exception:
                    pass

    def _schedule_poll(self):
        if self._poll_after_id is not None:
            try:
                self.frame.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None
        self._poll()

    def _poll(self):
        try:
            lines = []
            while True:
                try:
                    session_id, kind, item = self.queue.get_nowait()
                except queue.Empty:
                    break
                if session_id != self._session_id:
                    continue
                if kind == 'exit':
                    if self.running:
                        self.running = False
                        self._set_hint("logcat stream ended (device disconnected?).")
                    continue
                if kind == 'line':
                    lines.append(item)
            if lines:
                self._handle_new_lines(lines)
        finally:
            try:
                if self.frame.winfo_exists() and self.running:
                    self._poll_after_id = self.frame.after(100, self._poll)
                else:
                    self._poll_after_id = None
            except Exception:
                self._poll_after_id = None

    def _handle_new_lines(self, lines):
        new_visible = []
        with self.buffer_lock:
            for raw in lines:
                line = raw.rstrip('\r\n')
                level = parse_brief_level(line)
                self.buffer.append((line, level))
                if self._line_visible(line, level):
                    new_visible.append((line, level))
        if self.paused:
            self._update_status()
            return
        # Cap a single batch to keep the UI responsive on log bursts.
        if len(new_visible) > MAX_RENDER_LINES:
            self._refilter()
            return
        self._append_lines_batch(new_visible)
        self._update_status()
        if self.autoscroll.get() and new_visible:
            try:
                self.log_text.see(tk.END)
            except Exception:
                pass
