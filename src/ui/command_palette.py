"""Ctrl+K command palette over the menu tree and the action registry.

One small launcher instead of more chrome: every menubar command (with its
menu path) plus the registry-only actions is searchable; typing filters
fuzzy (substring then subsequence), Return or double-click runs the entry
the same way the menu itself would. Disabled entries stay listed and marked
so they are discoverable even while they wait for a device.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from .action_registry import ACTIONS
from .dpi import setup_window_dpi

_MAX_RESULTS = 14


def _score(display: str, query: str):
    """Relevance of one display path to the typed query ('None' filters out).

    A plain substring scores by how early it starts; a subsequence (ordered
    initials, 'cb' -> Command > Backup...) scores lower. Earlier matches
    dominate, tighter gaps beat looser ones.
    """
    if not query:
        return 0
    text = display.lower()
    query = query.lower()
    index = text.find(query)
    if index >= 0:
        return 1000 - index
    position = -1
    gaps = 0
    for char in query:
        found = text.find(char, position + 1)
        if found < 0:
            return None
        gaps += (found - position - 1) if position >= 0 else found
        position = found
    return 400 - gaps


def _menu_items(menubar):
    """(display path, menu widget, entry index) for every command entry."""
    items = []
    for index in range(menubar.index('last') + 1):
        kind = menubar.type(index)
        if kind == 'cascade':
            label = menubar.entrycget(index, 'label')
            submenu = menubar.nametowidget(menubar.entrycget(index, 'menu'))
            for path, menu, entry in _menu_items(submenu):
                items.append((f'{label} > {path}', menu, entry))
        elif kind == 'command':
            label = menubar.entrycget(index, 'label')
            items.append((label, menubar, index))
    return items


class CommandPaletteDialog(tk.Toplevel):
    def __init__(self, main_window):
        super().__init__(main_window.root)
        self.title('Command Palette')
        self.transient(main_window.root)
        self.resizable(False, False)

        self._main_window = main_window
        self._entries = []          # (display, runnable, disabled)
        self._displayed = []        # indexes into _entries, scored order

        self._build_items()

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        self._query_var = tk.StringVar()
        self._query_var.trace_add('write', self._refilter)
        self._entry = ttk.Entry(frame, textvariable=self._query_var,
                                font=('Segoe UI', 10))
        self._entry.pack(fill=tk.X, pady=(0, 6))
        self._list = tk.Listbox(frame, height=_MAX_RESULTS, activestyle='none',
                                font=('Segoe UI', 10), selectmode=tk.SINGLE,
                                bd=0, highlightthickness=1)
        self._list.pack(fill=tk.BOTH, expand=True)
        self._list.bind('<Return>', lambda event: self._run_selected())
        self._list.bind('<Double-Button-1>', lambda event: self._run_selected())
        self._hint = ttk.Label(frame, text='Enter runs it - Escape closes',
                               font=('', 9, 'italic'))
        self._hint.pack(anchor='w', pady=(4, 0))

        self.bind('<Escape>', lambda event: self._close())
        self._entry.bind('<Escape>', lambda event: self._close())
        self._entry.bind('<Down>', self._move(1))
        self._entry.bind('<Up>', self._move(-1))
        self._entry.bind('<Return>', lambda event: self._run_selected())

        setup_window_dpi(self, base_width=440, base_height=340,
                         min_width=420, min_height=280, parent=main_window.root)
        self._center(main_window.root)
        self.grab_set()
        self._entry.focus_set()
        self._refilter()

    def _build_items(self):
        """All palette sources: the menubar tree plus registry-only actions."""
        menubar_name = self._main_window.root.cget('menu')
        if menubar_name:
            menubar = self._main_window.root.nametowidget(menubar_name)
            for display, menu, index in _menu_items(menubar):
                try:
                    state = menu.entrycget(index, 'state')
                except tk.TclError:
                    state = 'normal'
                self._entries.append((display, ('menu', menu, index),
                                      state == 'disabled'))

        known = {display for display, _, _ in self._entries}
        for category, label, spec, _recordable in ACTIONS:
            display = f'{category} > {label}'
            if display not in known:
                self._entries.append((display, ('action', spec), False))

    def _refilter(self, *_):
        """Re-score the entries against the query and repaint the list."""
        self._list.delete(0, tk.END)
        self._displayed = []
        query = self._query_var.get().strip()

        scored = []
        for position, (display, runnable, disabled) in enumerate(self._entries):
            relevance = _score(display, query)
            if relevance is not None:
                scored.append((relevance, -position, display, runnable, disabled))
        scored.sort(reverse=True)

        for _, _, display, runnable, disabled in scored[:_MAX_RESULTS]:
            self._list.insert(tk.END, display + ('   (disabled)' if disabled else ''))
            self._displayed.append((display, runnable))
        if self._displayed:
            self._list.selection_set(0)
            self._list.activate(0)

    def _move(self, delta):
        def handler(_event):
            if not self._displayed:
                return 'break'
            current = int(self._list.curselection()[0]) if self._list.curselection() else 0
            target = max(0, min(len(self._displayed) - 1, current + delta))
            self._list.selection_clear(0, tk.END)
            self._list.selection_set(target)
            self._list.activate(target)
            self._list.see(target)
            return 'break'
        return handler

    def _run_selected(self):
        if not self._displayed:
            return 'break'
        _, runnable = self._displayed[int(self._list.curselection()[0])]
        self._close()
        try:
            if runnable[0] == 'menu':
                runnable[1].invoke(runnable[2])
            else:
                method_name, args = runnable[1]
                getattr(self._main_window, method_name)(*args)
        except Exception as e:
            messagebox.showerror('Command Palette',
                                 f'The command did not run: {e}',
                                 parent=self._main_window.root)
        return 'break'

    def _center(self, parent):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, screen_h // 5)
        self.geometry(f'+{x}+{y}')

    def _close(self):
        self._main_window._palette = None
        self.grab_release()
        self.destroy()


class _PaletteMixin:
    """_PaletteMixin for MainWindow (see main_window.py)."""

    def _show_command_palette(self):
        """Open the Ctrl+K launcher; refocus an already-open one."""
        palette = getattr(self, '_palette', None)
        if palette is not None and palette.winfo_exists():
            palette._entry.focus_set()
            return
        self._palette = CommandPaletteDialog(self)
