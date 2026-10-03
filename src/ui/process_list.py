"""Process list pane of the history window (left-hand tree)."""
"""Split from process_graph.py (MOVE-ONLY); ProcessHistoryWindow mixes this in."""

import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from .dpi import setup_window_dpi, scale_size
from .process_chart import (
    DEVICE_KEY, _format_size, _parse_size_bytes, _row_cpu,
)


class ProcessListMixin:
    """Process list pane of the history window."""

    def _create_list(self, parent):
        columns = ('CPU%', 'Memory', 'PID')
        self.tree = ttk.Treeview(parent, columns=columns, show='tree headings',
                                 selectmode='browse')
        self.tree.heading('#0', text='Process')
        for column in columns:
            self.tree.heading(column, text=column)
        self.tree.column('#0', width=scale_size(230, self), stretch=True)
        self.tree.column('CPU%', width=scale_size(80, self), anchor='e')
        self.tree.column('Memory', width=scale_size(90, self), anchor='e')
        self.tree.column('PID', width=scale_size(80, self), anchor='e')

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

    # --- the list ----------------------------------------------------------
    def _rebuild_list(self, processes, memory_totals):
        """Rewrite the rows from the reading just taken, keeping the selection."""
        selected = self._keys.get(self.tree.selection()[0] if self.tree.selection() else '')

        for item in self.tree.get_children(''):
            self.tree.delete(item)
        self._keys.clear()

        device_cpu, device_memory = self._latest.get(DEVICE_KEY, (0.0, 0))
        device_item = self.tree.insert(
            '', tk.END, text='Device totals', open=True,
            values=(f'{device_cpu:.1f}%', _format_size(device_memory), ''))
        self._keys[device_item] = DEVICE_KEY
        self._total_memory = int(memory_totals.get('total_bytes') or 0)

        root = self.tree.insert('', tk.END, text='Processes', open=True)
        self._keys[root] = DEVICE_KEY

        try:
            limit = max(1, int(self.top_var.get()))
        except (TypeError, ValueError):
            limit = 50

        ordered = sorted(processes, key=lambda row: _row_cpu(row), reverse=True)[:limit]
        for process in ordered:
            pid = str(process.get('pid') or '')
            cpu, memory = self._latest.get(pid, (0.0, 0))
            item = self.tree.insert(
                root, tk.END, text=process.get('name') or pid,
                values=(f'{cpu:.1f}%', _format_size(memory), pid))
            self._keys[item] = pid

        target = None
        if selected:
            for item, key in self._keys.items():
                if key == selected:
                    target = item
                    break
        if target is None:
            target = device_item
            self.selected_key = DEVICE_KEY
        self.tree.selection_set(target)
        self.tree.focus(target)

    def _on_select(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        key = self._keys.get(selection[0])
        if key is None:
            return
        self.selected_key = key
        self._refresh_graph()

    def _selected_name(self):
        """The name shown against the selection, wherever it sits in the tree."""
        stack = list(self.tree.get_children(''))
        while stack:
            item = stack.pop(0)
            if self._keys.get(item) == self.selected_key:
                text = self.tree.item(item, 'text')
                if text not in ('Device totals', 'Processes'):
                    return text
            stack.extend(self.tree.get_children(item))
        return f'pid {self.selected_key}'
