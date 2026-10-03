"""MainWindow mixin: screenshot, recording, forwards, LLM/bug reports."""

import datetime
import os
import re
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .capture import take_screenshot, record_screen
from .forward_dialog import ForwardDialog
from .llm_report_dialog import LLMReportDialog, LLMReportProgressDialog
from .bugreport_dialog import BugReportDialog, BugReportProgressDialog


class _DiagMixin:
    """_DiagMixin for MainWindow (see main_window.py)."""

    def _take_screenshot(self):
        """Tools > Take Screenshot: one click, then a save dialog."""
        if not self._require_device():
            return
        take_screenshot(self.root, self.device_manager, self.selected_device,
                        self._set_status, self._show_error, self._show_info)

    def _record_screen(self):
        """Tools > Record Screen: parameter dialog, then record, pull and open."""
        if not self._require_device():
            return
        record_screen(self.root, self.device_manager, self.selected_device,
                      self._set_status, self._show_error, self._show_info)

    def _show_forward_dialog(self):
        """Open the port forward manager for the selected device."""
        if not self._require_device():
            return
        ForwardDialog(self.root, self.selected_device, self.device_manager, self._set_status)

    def _generate_llm_report(self):
        if not self._require_device():
            return
        
        device_id = self.selected_device
        progress_dialog = LLMReportProgressDialog(self.root, title=f"Generating LLM Report - {device_id}")
        
        def progress_cb(pct, msg):
            self.root.after(0, lambda: progress_dialog.update_progress(pct, msg))
            
        def task():
            try:
                report_text = self.device_manager.generate_llm_report(device_id, progress_callback=progress_cb)
                
                def on_done():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    if not progress_dialog.cancelled:
                        LLMReportDialog(self.root, device_id, report_text)
                        self._set_status(f"Generated LLM report for {device_id}")
                
                self.root.after(0, on_done)
            except Exception as e:
                err_msg = str(e)
                def on_error():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    self._show_error("LLM Report Generation Error", err_msg)
                self.root.after(0, on_error)
                
        threading.Thread(target=task, daemon=True).start()

    def _collect_bugreport(self):
        """Gather a bugreport from the device and brief the user on it."""
        if not self._require_device():
            return

        device_id = self.selected_device
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', device_id).strip() or 'device'
        working_copy = os.path.join(
            tempfile.gettempdir(), f'bugreport-{safe_id}-{stamp}.zip')

        # adb appends to a report it finds already there, so start from nothing.
        if os.path.exists(working_copy):
            try:
                os.remove(working_copy)
            except OSError:
                pass

        progress_dialog = BugReportProgressDialog(self.root, device_id)
        progress_dialog.start()
        self._set_status(f"Collecting a bug report from {device_id}...")

        def task():
            started = time.monotonic()
            try:
                self.device_manager.collect_bugreport(device_id, working_copy)
                elapsed = time.monotonic() - started
                briefing = self.device_manager.build_bugreport_briefing(
                    device_id, working_copy, elapsed)

                def on_done():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    # A collection left running in the background still has
                    # somewhere to land, so the briefing opens either way.
                    BugReportDialog(self.root, device_id, working_copy, briefing)
                    self._set_status(f"Bug report collected from {device_id}")

                self.root.after(0, on_done)
            except Exception as e:
                err_msg = str(e)

                def on_error():
                    if progress_dialog.winfo_exists():
                        progress_dialog.destroy()
                    self._show_error("Bug Report Error", err_msg)

                self.root.after(0, on_error)

        threading.Thread(target=task, daemon=True).start()

