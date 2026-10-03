"""MainWindow mixin: notebook tab switching and visibility."""

import tkinter as tk
from typing import Dict, List, Optional


class _TabsMixin:
    """_TabsMixin for MainWindow (see main_window.py)."""

    def _update_tab_visibility(self):
        if self.has_devices:
            self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.no_devices_frame.pack_forget()
            self._update_button_states()
            
            if self.selected_device and self.notebook.index('end') == 1:
                self.notebook.add(self.processes_tab, text="Processes")
                self.notebook.add(self.apps_tab, text="Applications")
                self.notebook.add(self.files_tab, text="Files")
                self.notebook.add(self.network_tab, text="Network")
                self.notebook.add(self.logcat_tab, text="Logcat")
                self.notebook.add(self.shell_tab, text="Shell")
                self.notebook.add(self.misc_tab, text="Developer Options")
            elif not self.selected_device:
                if hasattr(self, 'network_view'):
                    self.network_view.set_device(None)
                while self.notebook.index('end') > 1:
                    self.notebook.forget(1)
        else:
            self.device_tree.pack_forget()
            self.no_devices_frame.pack(fill=tk.BOTH, expand=True)
            self._update_button_states()
            
            if hasattr(self, 'network_view'):
                self.network_view.set_device(None)
            while self.notebook.index('end') > 1:
                self.notebook.forget(1)

    def _on_tab_changed(self, event=None):
        if not self.selected_device:
            return
            
        try:
            current_tab_id = self.notebook.select()
            if not current_tab_id:
                return
            tab_text = self.notebook.tab(current_tab_id, "text")

            if tab_text != "Network" and hasattr(self, 'network_view'):
                self.network_view.stop_polling()
            if tab_text != "Logcat" and hasattr(self, 'logcat_view'):
                self.logcat_view.stop()
            
            # Debounce tab activation so rapid tab clicking doesn't flood ADB and Tkinter
            if getattr(self, '_tab_change_timer', None) is not None:
                try:
                    self.root.after_cancel(self._tab_change_timer)
                except Exception:
                    pass
                self._tab_change_timer = None

            self._tab_change_timer = self.root.after(120, lambda: self._activate_tab_safely(current_tab_id, tab_text))
        except Exception:
            pass

    def _activate_tab_safely(self, target_tab_id, expected_tab_text):
        self._tab_change_timer = None
        if not self.selected_device:
            return
        try:
            if not self.notebook.winfo_exists():
                return
            current_tab_id = self.notebook.select()
            if current_tab_id != target_tab_id:
                return
            tab_text = self.notebook.tab(current_tab_id, "text")
            if tab_text != expected_tab_text:
                return

            if tab_text == "Processes":
                self._refresh_processes()
            elif tab_text == "Applications":
                self._refresh_apps()
            elif tab_text == "Files":
                self.file_manager.set_device(self.selected_device, force_refresh=True)
            elif tab_text == "Network":
                self.network_view.set_device(self.selected_device)
            elif tab_text == "Logcat":
                self.logcat_view.set_device(
                    self.selected_device, force_refresh=True, autostart=True)
            elif tab_text == "Shell":
                self.shell_view.set_device(self.selected_device)
            elif tab_text == "Developer Options":
                self.misc_tab.set_device(self.selected_device)
        except Exception:
            pass

    def _open_shell_tab(self):
        """Focus the Shell tab (Tools > Open Shell)."""
        if not self._require_device():
            return
        if self.shell_tab not in self.notebook.tabs():
            return
        self.notebook.select(self.shell_tab)
        self.shell_view.set_device(self.selected_device)
        self.shell_view.focus_input()

