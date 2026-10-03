"""Sortable table widget used by the network inspector."""

import tkinter as tk
from tkinter import ttk

from .network_format import TABLE_HEIGHT


class _SortableTree(ttk.Frame):
    """A treeview whose rows reorder when a heading is clicked."""

    def __init__(self, parent, columns, sort_map=None, default_sort=None,
                 default_reverse=False, height=TABLE_HEIGHT):
        super().__init__(parent)
        self.sort_map = sort_map or {}
        self.sort_column = None
        self.sort_reverse = False
        self.rows = {}

        self.tree = ttk.Treeview(
            self, columns=[key for key, _, _, _ in columns],
            show='headings', height=height, selectmode='browse')

        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title,
                              command=lambda column=key: self.sort_by(column))
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == columns[0][0]))

        vertical = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vertical.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        if default_sort:
            self.sort_column = default_sort
            self.sort_reverse = default_reverse

    def clear(self):
        self.rows.clear()
        for item in self.tree.get_children(''):
            self.tree.delete(item)

    def fill(self, rows, formatter):
        """Show each row, keeping the raw data so the sort has something to use."""
        yview = self.tree.yview()
        self.clear()
        for row in rows:
            item = self.tree.insert('', 'end', values=formatter(row))
            self.rows[item] = row
        self._apply_sort()
        if yview and yview[0] > 0:
            try:
                self.tree.yview_moveto(yview[0])
            except Exception:
                pass

    def _value_for(self, row, column):
        getter = self.sort_map.get(column)
        if getter is None:
            return row.get(column)
        return getter(row)

    def _apply_sort(self):
        if not self.sort_column:
            return

        column = self.sort_column

        def sort_key(item):
            value = self._value_for(self.rows.get(item, {}), column)
            if isinstance(value, (int, float)):
                return (1, float(value))
            return (0, '' if value is None else str(value).lower())

        items = list(self.rows)
        items.sort(key=sort_key, reverse=self.sort_reverse)
        for index, item in enumerate(items):
            self.tree.move(item, '', index)

    def sort_by(self, column):
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = self._opens_on_numbers(column)
        self._apply_sort()

    def _opens_on_numbers(self, column):
        for row in self.rows.values():
            return isinstance(self._value_for(row, column), (int, float))
        return False
