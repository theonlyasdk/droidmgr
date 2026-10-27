"""DropBox crash browser: reads and browses one device's DropBox entries.

`dumpsys dropbox --print` returns every entry the DropBoxManager still
holds - application crashes and ANRs, but system events and other tags as
well. The dialog lists them in a sortable table and shows the selected
entry's text below.
"""

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from .dpi import setup_window_dpi
from .network_format import TABLE_HEIGHT, _format_bytes
from .network_tables import _SortableTree

# Only this much of one entry is put into the detail pane, so a giant blob
# stays usable; Copy still hands over the full saved text.
_MAX_DETAIL_CHARS = 500 * 1024

_ALL_TAGS = 'All tags'


class DropboxBrowserDialog(tk.Toplevel):
    """Lists the DropBox entries for one device with their full text."""

    def __init__(self, root, device_id, device_manager,
                 set_status_callback=None, show_error_callback=None,
                 require_device_callback=None):
        super().__init__(root)
        self.title(f"DropBox Browser - {device_id}")
        self.device_id = device_id
        self.device_manager = device_manager

        self._set_status = set_status_callback or (lambda message: None)
        if show_error_callback is not None:
            self._show_error = show_error_callback
        else:
            def _default_error(title, message):
                messagebox.showerror(title, message, parent=self)
            self._show_error = _default_error
        self._require_device = require_device_callback

        self._busy = False
        self._entries = []       # every parsed entry dict, newest last
        self._detail_data = ''   # full text of the entry in the detail pane

        self._create_widgets()
        self._refresh()

        setup_window_dpi(self, base_width=760, base_height=560,
                         min_width=540, min_height=400, parent=root)

        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda event: self.destroy())

    # -- widget construction -------------------------------------------

    def _create_widgets(self):
        toolbar = ttk.Frame(self, padding=(10, 10, 10, 0))
        toolbar.pack(fill=tk.X)

        self.refresh_btn = ttk.Button(toolbar, text="Refresh",
                                      command=self._refresh)
        self.refresh_btn.pack(side=tk.LEFT)

        ttk.Label(toolbar, text="Tag:").pack(side=tk.LEFT, padx=(14, 4))
        self.tag_var = tk.StringVar(value=_ALL_TAGS)
        self.tag_combo = ttk.Combobox(toolbar, textvariable=self.tag_var,
                                      state='readonly', width=24,
                                      values=(_ALL_TAGS,))
        self.tag_combo.pack(side=tk.LEFT)
        self.tag_combo.bind('<<ComboboxSelected>>',
                            lambda event: self._refill_rows())

        ttk.Button(toolbar, text="Close", command=self.destroy,
                   width=10).pack(side=tk.RIGHT)

        pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 4))

        # Entry list: sort by clicking a heading, the newest entry first.
        table_frame = ttk.Frame(pane)
        self.table = _SortableTree(
            table_frame,
            [
                ('tag', 'Tag', 190, 'w'),
                ('time', 'Time', 165, 'w'),
                ('size', 'Bytes', 90, 'e'),
            ],
            sort_map={
                'tag': lambda row: row['tag'],
                'time': lambda row: row['time'] or 0,
                'size': lambda row: row['size'],
            },
            default_sort='time',
            default_reverse=True,
            height=TABLE_HEIGHT,
            empty_text='No DropBox entries on this device',
        )
        self.table.pack(fill=tk.BOTH, expand=True)
        pane.add(table_frame, weight=3)
        self.table.tree.bind('<<TreeviewSelect>>',
                             lambda event: self._show_selected())

        # Detail pane: the selected entry's text, read-only.
        detail = ttk.LabelFrame(pane, text='Entry text', padding=6)
        text_box = ttk.Frame(detail)
        text_box.pack(fill=tk.BOTH, expand=True)

        self.detail_text = tk.Text(text_box, wrap='none', font=('Consolas', 9),
                                   state=tk.DISABLED)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vertical = ttk.Scrollbar(text_box, orient=tk.VERTICAL,
                                 command=self.detail_text.yview)
        vertical.pack(side=tk.RIGHT, fill=tk.Y)
        self.detail_text.configure(yscrollcommand=vertical.set)

        horizontal = ttk.Scrollbar(detail, orient=tk.HORIZONTAL,
                                   command=self.detail_text.xview)
        horizontal.pack(fill=tk.X)
        self.detail_text.configure(xscrollcommand=horizontal.set)

        buttons = ttk.Frame(detail)
        buttons.pack(fill=tk.X, pady=(4, 0))
        self.copy_btn = ttk.Button(buttons, text="Copy", width=10,
                                   command=self._copy_detail,
                                   state=tk.DISABLED)
        self.copy_btn.pack(side=tk.RIGHT)
        self.detail_note_var = tk.StringVar(
            value='Select an entry to read its text.')
        ttk.Label(buttons, textvariable=self.detail_note_var,
                  foreground='gray').pack(side=tk.LEFT)
        pane.add(detail, weight=2)

        # Dialog's own status line for refresh progress and row counts.
        status_frame = ttk.Frame(self, padding=(10, 0, 10, 8))
        status_frame.pack(fill=tk.X)
        self.status_var = tk.StringVar(value='')
        ttk.Label(status_frame, textvariable=self.status_var,
                  foreground='gray').pack(anchor='w')

    # -- loading -------------------------------------------------------

    def _refresh(self):
        """Read the entries from the device, in a worker thread."""
        if self._busy:
            return
        if self._require_device is not None and not self._require_device():
            return   # the callback already told the user why

        self._busy = True
        self.refresh_btn.configure(state=tk.DISABLED)
        message = f'Reading DropBox entries from {self.device_id}...'
        self.status_var.set(message)
        self._set_status(message)

        def task():
            entries, error = [], ''
            try:
                entries = self.device_manager.get_dropbox_entries(self.device_id)
            except Exception as e:
                error = str(e)
            self.after(0, lambda: self._apply_entries(entries, error))

        threading.Thread(target=task, daemon=True).start()

    def _apply_entries(self, entries, error):
        self._busy = False
        if not self.winfo_exists():
            return
        self.refresh_btn.configure(state=tk.NORMAL)

        if error:
            self.status_var.set('Reading the DropBox entries failed.')
            self._show_error('DropBox Browser Error', error)
            return

        self._entries = list(entries)
        self._update_tag_combo()
        self._refill_rows()
        self._set_status(
            f'Read {len(self._entries)} DropBox entr'
            f'{"y" if len(self._entries) == 1 else "ies"} from {self.device_id}')

    def _update_tag_combo(self):
        """Tag choice list, count descending, from the parsed entries."""
        counts = {}
        for entry in self._entries:
            counts[entry['tag']] = counts.get(entry['tag'], 0) + 1
        tags = [tag for tag, count in
                sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
        self.tag_combo.configure(values=[_ALL_TAGS] + tags)
        if self.tag_var.get() != _ALL_TAGS and self.tag_var.get() not in tags:
            self.tag_var.set(_ALL_TAGS)

    # -- filtering, display --------------------------------------------

    def _refill_rows(self):
        """Rebuild the table from the kept entries for the chosen tag."""
        picked = self.tag_var.get()
        rows = [entry for entry in self._entries
                if picked == _ALL_TAGS or picked == entry['tag']]
        self.table.fill(rows, self._format_row)

        if picked == _ALL_TAGS:
            count = len(self._entries)
            self.status_var.set(
                f'{count} DropBox entr'
                f'{"y" if count == 1 else "ies"} for {self.device_id}')
        else:
            self.status_var.set(
                f'{len(rows)} of {len(self._entries)} entr'
                f'{"y" if len(self._entries) == 1 else "ies"} with tag '
                f"'{picked}' for {self.device_id}")

    @staticmethod
    def _format_row(row):
        """The values a table row shows for one entry dict."""
        shown_time = ''
        if row['time']:
            shown_time = datetime.fromtimestamp(
                row['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        return (row['tag'], shown_time, _format_bytes(row['size']))

    def _show_selected(self):
        """Put the selected entry's text into the detail pane."""
        selection = self.table.tree.selection()
        entry = self.table.rows.get(selection[0]) if selection else None
        if entry is None:
            return

        self._detail_data = entry['data'] or ''
        display = self._detail_data[:_MAX_DETAIL_CHARS]
        if len(self._detail_data) > _MAX_DETAIL_CHARS:
            display += '\n\n(truncated for display)'

        try:
            self.detail_text.configure(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.insert('1.0', display)
            self.detail_text.configure(state=tk.DISABLED)
            self.detail_text.yview_moveto(0.0)
        except tk.TclError:
            return

        shown_time = self._format_row(entry)[1] or '(no timestamp)'
        self.detail_note_var.set(
            f"{entry['tag']} at {shown_time} - {_format_bytes(entry['size'])}")
        self.copy_btn.configure(state=tk.NORMAL)

    # -- actions -------------------------------------------------------

    def _copy_detail(self):
        """Copy the full entry text, even when the pane shows a truncated one."""
        try:
            self.clipboard_clear()
            self.clipboard_append(self._detail_data)
            self.copy_btn.configure(text="Copied", state=tk.DISABLED)
            self.after(1500, self._restore_copy_button)
        except tk.TclError:
            pass

    def _restore_copy_button(self):
        try:
            self.copy_btn.configure(text="Copy", state=tk.NORMAL)
        except tk.TclError:
            pass
