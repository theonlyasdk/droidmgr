"""Wireshark-style packet-list widget used by the network inspector.

Every table on the Network tab borrows Wireshark's habits: a dense, striped
row list with a solid-blue selected row, an optional display filter that
narrows the visible rows WITHOUT re-querying the device (the raw rows stay
in memory, so clearing the filter restores them), a 'N of M shown' capture
counter, and a centered empty state.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import scale_size
from .network_format import TABLE_HEIGHT

# The row blue Wireshark highlights the selected packet with.
_SELECTED_BG = '#0b62c4'

# Very light stripe for odd rows; Wireshark's list, not a spreadsheet.
_STRIPE_BG = '#f2f6fb'


def _wire_list_style(widget):
    """Configure the shared 'Wire.Treeview' style: dense, striped, blue select."""
    style = ttk.Style(widget)
    try:
        rowheight = max(18, scale_size(19, widget))
        style.configure('Wire.Treeview',
                        rowheight=rowheight,
                        font=('Segoe UI', 9),
                        background='#ffffff',
                        fieldbackground='#ffffff')
        style.configure('Wire.Treeview.Heading',
                        font=('Segoe UI', 9, 'bold'))
        style.map('Wire.Treeview',
                  background=[('selected', _SELECTED_BG)],
                  foreground=[('selected', '#ffffff')])
    except Exception:
        pass


class _SortableTree(ttk.Frame):
    """A treeview whose rows reorder when a heading is clicked."""

    def __init__(self, parent, columns, sort_map=None, default_sort=None,
                 default_reverse=False, height=TABLE_HEIGHT,
                 empty_text='No data captured yet', tag_fn=None):
        super().__init__(parent)
        self.sort_map = sort_map or {}
        self.sort_column = None
        self.sort_reverse = False
        self.rows = {}
        self.row_tags = {}
        self.raw_rows = []   # every row of the last capture, filter or not
        self.formatter = None
        self.filter_fn = None
        self.status_var = None
        self.after_fill = None
        self.tag_fn = tag_fn

        _wire_list_style(self)

        self.tree = ttk.Treeview(
            self, columns=[key for key, _, _, _ in columns],
            show='headings', height=height, selectmode='browse',
            style='Wire.Treeview')

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

        self.tree.tag_configure('even', background='#ffffff')
        self.tree.tag_configure('odd', background=_STRIPE_BG)

        # Wireshark coloring rules; configured even where unused, so callers
        # can hand back any tag name and it renders with its color.
        self.tree.tag_configure('very-heavy', foreground='#c62828',
                                font=('Segoe UI', 9, 'bold'))
        self.tree.tag_configure('heavy', foreground='#e65100')
        self.tree.tag_configure('established', foreground='#1d7d34')
        self.tree.tag_configure('listening', foreground='#0b62c4')
        self.tree.tag_configure('opening', foreground='#b25b00')
        self.tree.tag_configure('closing', foreground='#8a9199')
        self.tree.tag_configure('dropped', foreground='#c62828')
        self.tree.tag_configure('degraded', foreground='#b25b00')

        self.empty_text = empty_text
        self._empty = tk.Label(
            self.tree, text=empty_text, foreground='gray', background='#ffffff',
            anchor='center')
        self._empty_visible = False
        self.shown = 0        # rows visible after the display filter
        self.total = 0        # rows the device reported
        self._closed = False

        if default_sort:
            self.sort_column = default_sort
            self.sort_reverse = default_reverse

        self.bind('<Destroy>', self._on_destroy, add='+')

    # -- live display filter -------------------------------------------

    def set_filter_fn(self, fn):
        """The filter text supplier; None disables filtering."""
        self.filter_fn = fn

    def set_status_var(self, var):
        """A tk.StringVar updated with '<shown>' after every refill."""
        self.status_var = var

    def force_refill(self):
        """Rebuild from the kept capture (display filter changed)."""
        if self.formatter is None or not self.raw_rows:
            return
        kept = list(self.raw_rows)
        self.fill(kept, self.formatter)

    def _current_filter(self):
        if self.filter_fn is None:
            return ''
        try:
            return (self.filter_fn() or '').strip().lower()
        except Exception:
            return ''

    def _matches(self, row, needle):
        """Space-separated terms, all of which must appear somewhere."""
        blob = ' '.join(
            f'{key}={row[key]}' for key in row if row[key] is not None
        ).lower()
        return all(term in blob for term in needle.split())

    def _value_for(self, row, column):
        getter = self.sort_map.get(column)
        if getter is None:
            return row.get(column)
        return getter(row)

    # -- row list --------------------------------------------------------

    def fill(self, rows, formatter=None):
        """Replace the rows; formatter maps a raw dict to display values."""
        if formatter is not None:
            self.formatter = formatter
        else:
            formatter = self.formatter or (lambda row: ('',))

        self.raw_rows = list(rows)
        self.rows.clear()
        self.row_tags.clear()

        query = self._current_filter() if self.filter_fn else ''
        shown = 0
        for row in rows:
            if query and not self._matches(row, query):
                continue
            special = tuple(self.tag_fn(row)) if self.tag_fn else ()
            item = self.tree.insert('', 'end', values=formatter(row),
                                    tags=special)
            self.rows[item] = row
            self.row_tags[item] = special
            shown += 1

        self.shown = shown
        self.total = len(rows)

        self._apply_sort()
        self._reapply_stripes()

        if self.status_var is not None:
            try:
                self.status_var.set(str(shown))
            except Exception:
                pass

        self._refresh_empty()

        if self.after_fill is not None:
            try:
                self.after_fill(shown, len(rows))
            except Exception:
                pass

    def clear(self):
        self.raw_rows = []
        self.rows.clear()
        self.row_tags.clear()
        self.shown = 0
        self.total = 0
        for item in self.tree.get_children(''):
            self.tree.delete(item)
        self._refresh_empty()

    # -- sorting and striping -------------------------------------------

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
        self._reapply_stripes()

    def _opens_on_numbers(self, column):
        for row in self.rows.values():
            return isinstance(self._value_for(row, column), (int, float))
        return False

    def _reapply_stripes(self):
        """Keep the zebra correct in the order the rows are shown in."""
        for index, item in enumerate(self.tree.get_children('')):
            stripe = 'odd' if index % 2 else 'even'
            special = self.row_tags.get(item, ())
            self.tree.item(item, tags=(stripe,) + special)

    # -- empty state -----------------------------------------------------

    def _refresh_empty(self):
        """Centered 'No data captured yet' / 'No rows match the filter'."""
        if self._closed:
            return
        if self.shown > 0:
            if self._empty_visible:
                try:
                    self._empty.place_forget()
                except Exception:
                    pass
                self._empty_visible = False
            return
        if self.total and not self.shown:
            self._empty.config(text='No rows match the display filter')
        else:
            self._empty.config(text=self.empty_text)
        try:
            if not self._empty_visible:
                self._empty.place(relx=0.5, rely=0.5, anchor='center')
                self._empty_visible = True
        except Exception:
            pass

    def _on_destroy(self, event=None):
        self._closed = True
