"""MainWindow mixin: selection getters and info dialogs."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional
from .app_info_dialog import AppInfoDialog, ProcessInfoDialog
from .main_utils import _app_sort_key, _parse_memory


class _SelectionMixin:
    """_SelectionMixin for MainWindow (see main_window.py)."""

    def _get_selected_packages(self) -> List[str]:
        """Every selected package, in the order the rows appear in the view."""
        selected = set(self.app_tree.selection())
        packages = []
        for item_id in self.app_tree.get_children(''):
            if item_id not in selected:
                continue
            values = self.app_tree.item(item_id, 'values')
            if values and len(values) >= 2 and values[1]:
                packages.append(values[1])
        return packages

    def _get_selected_package(self) -> Optional[str]:
        """The package the single-app actions act on.

        With several rows selected this is the focused one, so Ctrl+clicking a
        pile of apps and then hitting Start still does something predictable.
        """
        packages = self._get_selected_packages()
        if not packages:
            return None

        focused = None
        focus_id = self.app_tree.focus()
        if focus_id:
            values = self.app_tree.item(focus_id, 'values')
            if values and len(values) >= 2:
                focused = values[1]

        return focused if focused in packages else packages[0]

    def _get_visible_app_types(self) -> Dict[str, str]:
        """Package -> Type column value for every app currently listed.

        The type comes from the install path the device reports, so unlike the
        name heuristic it holds for any package, vendor ones included.
        """
        types: Dict[str, str] = {}
        for item_id in self.app_tree.get_children(''):
            values = self.app_tree.item(item_id, 'values')
            if values and len(values) >= 3 and values[1]:
                types[values[1]] = values[2]
        return types

    def _show_process_info(self, event=None):
        selection = self.process_tree.selection()
        if not selection:
            return
            
        item_id = selection[0]
        values = self.process_tree.item(item_id, 'values')
        if not values:
            return
            
        pid, user, cpu, mem, name = values
        
        proc_info = {
            'pid': pid,
            'user': user,
            'cpu': cpu,
            'mem': mem,
            'name': name
        }
        
        # Check if the process name looks like a package or is in the installed app list
        is_package_guess = '.' in name and not name.startswith('/') and '[' not in name
        
        if is_package_guess:
            def task():
                try:
                    info = self.device_manager.adb.get_app_info(self.selected_device, name)
                    self.root.after(0, lambda: AppInfoDialog(self.root, info, self.selected_device, self.device_manager))

                except Exception:
                    self.root.after(0, lambda: ProcessInfoDialog(self.root, proc_info))
            threading.Thread(target=task, daemon=True).start()
        else:
            ProcessInfoDialog(self.root, proc_info)

    def _copy_processes_list(self):
        items = self.process_tree.get_children()
        if not items:
            self._show_warning("No processes to copy")
            return
            
        headers = ['PID', 'User', 'CPU%', 'Memory', 'Process Name']
        
        # Get all rows
        rows = []
        for item in items:
            vals = self.process_tree.item(item, 'values')
            if vals:
                rows.append([str(v) for v in vals])
                
        if not rows:
            self._show_warning("No process list data available to copy")
            return
            
        # Determine maximum width for each column to align nicely
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(val))
                    
        # Generate formatted markdown table
        header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
        separator_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
        
        table_lines = [header_line, separator_line]
        for row in rows:
            row_line = "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
            table_lines.append(row_line)
            
        table_text = "\n".join(table_lines)
        
        self.root.clipboard_clear()
        self.root.clipboard_append(table_text)
        self._set_status("Process list copied as formatted table!")
        
        self.copy_processes_btn.config(text="Copied!")
        self.root.after(2000, lambda: self.copy_processes_btn.config(text="Copy Process List"))



    def _sort_apps_by_column(self, col):
        """Sort the applications list by a heading click, toggling the direction."""
        if getattr(self, 'app_sort_col', None) == col:
            self.app_sort_reverse = not self.app_sort_reverse
        else:
            self.app_sort_col = col
            # Biggest first for Size, alphabetical for everything else
            self.app_sort_reverse = col == 'Size'

        self._apply_app_sort()
        direction = 'descending' if self.app_sort_reverse else 'ascending'
        self._set_status(f"Sorted applications by {col} ({direction})")

    def _apply_app_sort(self):
        """Reorder the rows already listed, without re-querying the device."""
        col = getattr(self, 'app_sort_col', None)
        if not col:
            return

        if getattr(self, '_apps_data', None):
            self._apps_data.sort(key=lambda app: _app_sort_key(app, col),
                                 reverse=self.app_sort_reverse)
            selected_pkgs = set(self._get_selected_packages())
            yview = self.app_tree.yview()
            self._apply_app_filter(restore_selected=selected_pkgs, restore_yview=yview)
            return

        def row_key(item_id):
            val = self.app_tree.set(item_id, col)
            if col == 'Size':
                try:
                    return _parse_memory(val)
                except Exception:
                    return 0
            return val.lower()

        items = [(row_key(item_id), item_id) for item_id in self.app_tree.get_children('')]
        items.sort(key=lambda pair: pair[0], reverse=self.app_sort_reverse)
        for index, (_, item_id) in enumerate(items):
            self.app_tree.move(item_id, '', index)

