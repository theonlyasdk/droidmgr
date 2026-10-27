"""Port forward manager: adb forward and adb reverse, per device."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .dpi import setup_window_dpi, scale_size

# adb itself decides which endpoint forms it accepts; the dialog only insists
# that both ends are written as 'kind:name'.
_SCOPE_ALL = 'All'
_SCOPE_FORWARD = 'Forward'
_SCOPE_REVERSE = 'Reverse'


class ForwardDialog(tk.Toplevel):
    """Lists and edits the port forwards for one device."""

    def __init__(self, parent, device_id, device_manager, set_status_callback=None):
        super().__init__(parent)
        self.title(f"Port Forwarding - {device_id}")
        self.device_id = device_id
        self.device_manager = device_manager
        self._set_status = set_status_callback or (lambda message: None)

        self.resizable(True, True)
        self.transient(parent)

        self._busy = False
        self._entries = {}
        self._all_rows = []
        self._config_obj = None

        self._create_widgets()
        self._refresh_sets()
        self._refresh()

        setup_window_dpi(self, base_width=560, base_height=530,
                         min_width=480, min_height=450, parent=parent)

        self.bind('<Escape>', lambda e: self.destroy())
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    # -- widget construction -------------------------------------------

    def _create_widgets(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(main)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(toolbar, text="Show:").pack(side=tk.LEFT, padx=(0, 4))
        self.scope_var = tk.StringVar(value=_SCOPE_ALL)
        self.scope_combo = ttk.Combobox(toolbar, textvariable=self.scope_var,
                                        values=(_SCOPE_ALL, _SCOPE_FORWARD, _SCOPE_REVERSE),
                                        state='readonly', width=10)
        self.scope_combo.pack(side=tk.LEFT)
        self.scope_combo.bind('<<ComboboxSelected>>', lambda e: self._refresh())

        ttk.Button(toolbar, text="Refresh", command=self._refresh).pack(side=tk.RIGHT)

        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('direction', 'local', 'remote')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings',
                                 selectmode='extended')
        for column, text, width in (('direction', 'Direction', 90),
                                    ('local', 'Local', 170),
                                    ('remote', 'Remote', 170)):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=scale_size(width, self), anchor='w')
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<Delete>', lambda e: self._remove_selected())

        add_frame = ttk.LabelFrame(main, text="Add a forward", padding=10)
        add_frame.pack(fill=tk.X, pady=(10, 0))
        add_frame.columnconfigure(1, weight=1)
        add_frame.columnconfigure(3, weight=1)

        ttk.Label(add_frame, text="Direction:").grid(row=0, column=0, sticky='w', padx=(0, 6))
        self.direction_var = tk.StringVar(value=_SCOPE_FORWARD)
        direction_combo = ttk.Combobox(add_frame, textvariable=self.direction_var,
                                       values=(_SCOPE_FORWARD, _SCOPE_REVERSE),
                                       state='readonly', width=10)
        direction_combo.grid(row=0, column=1, sticky='w')
        self.help_var = tk.StringVar(
            value="host port -> device port" if self.direction_var.get() == _SCOPE_FORWARD
            else "device port -> host port")
        ttk.Label(add_frame, textvariable=self.help_var, foreground='gray').grid(
            row=0, column=2, columnspan=2, sticky='w', padx=(16, 0))
        direction_combo.bind('<<ComboboxSelected>>', lambda e: self._update_direction_hint())

        self.local_var = tk.StringVar()
        self.remote_var = tk.StringVar()
        ttk.Label(add_frame, text="Local:").grid(row=1, column=0, sticky='w', padx=(0, 6), pady=(8, 0))
        local_entry = ttk.Entry(add_frame, textvariable=self.local_var, width=18)
        local_entry.grid(row=1, column=1, sticky='ew', pady=(8, 0))
        ttk.Label(add_frame, text="Remote:").grid(row=1, column=2, sticky='w', padx=(10, 6), pady=(8, 0))
        remote_entry = ttk.Entry(add_frame, textvariable=self.remote_var, width=18)
        remote_entry.grid(row=1, column=3, sticky='ew', pady=(8, 0))
        local_entry.bind('<Return>', lambda e: self._add_forward())
        remote_entry.bind('<Return>', lambda e: self._add_forward())

        saved_sets = ttk.LabelFrame(main, text="Saved sets", padding=10)
        saved_sets.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(saved_sets, text="Set:").pack(side=tk.LEFT, padx=(0, 6))
        self.set_var = tk.StringVar()
        self.set_combo = ttk.Combobox(saved_sets, textvariable=self.set_var,
                                      state='readonly', width=18)
        self.set_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(saved_sets, text="Save set...",
                   command=self._save_set).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(saved_sets, text="Apply set...",
                   command=self._apply_set).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(saved_sets, text="Delete set...",
                   command=self._delete_set).pack(side=tk.LEFT, padx=(6, 0))

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(10, 0))
        self.add_btn = ttk.Button(buttons, text="Add", command=self._add_forward)
        self.add_btn.pack(side=tk.LEFT)
        self.remove_btn = ttk.Button(buttons, text="Remove Selected", command=self._remove_selected)
        self.remove_btn.pack(side=tk.LEFT, padx=6)
        self.remove_all_btn = ttk.Button(buttons, text="Remove All", command=self._remove_all)
        self.remove_all_btn.pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy, width=10).pack(side=tk.RIGHT)

        self.summary_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self.summary_var, foreground='gray').pack(
            anchor='w', pady=(8, 0))

    def _update_direction_hint(self):
        forward = self.direction_var.get() == _SCOPE_FORWARD
        self.help_var.set("host port -> device port" if forward else "device port -> host port")

    # -- saved sets ------------------------------------------------------

    def _config(self):
        """The shared ConfigManager, created on first use; None if unavailable."""
        if self._config_obj is None:
            try:
                from core.config_manager import ConfigManager
                self._config_obj = ConfigManager()
            except Exception:
                self._config_obj = False
        return self._config_obj if self._config_obj else None

    def _load_sets(self):
        """Saved forward sets, each ``{'name', 'rows': [{'local', 'remote', 'type'}]}``."""
        config = self._config()
        loaded = config.get('forwards', 'sets', []) if config else []
        sets = []
        for entry in loaded or []:
            name = str(entry.get('name') or '').strip()
            rows = []
            for item in entry.get('rows') or []:
                local = str(item.get('local') or '').strip()
                remote = str(item.get('remote') or '').strip()
                if local and remote:
                    rows.append({'local': local, 'remote': remote,
                                 'type': item.get('type') or 'forward'})
            if name and rows:
                sets.append({'name': name, 'rows': rows})
        return sets

    def _refresh_sets(self):
        names = [entry['name'] for entry in self._load_sets()]
        self.set_combo.configure(values=names)
        if self.set_var.get() not in names:
            self.set_var.set('')

    def _save_set(self):
        """Capture this device's currently active rules as a named set."""
        rows = [{'local': row['local'], 'remote': row['remote'],
                 'type': 'reverse' if row['direction'] == _SCOPE_REVERSE
                 else 'forward'}
                for row in self._all_rows]
        if not rows:
            messagebox.showinfo(
                "Save Set",
                "This device has no active forwards or reverses to save.",
                parent=self)
            return
        name = simpledialog.askstring("Save Set", "Set name:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        sets = self._load_sets()
        existing = next((s for s in sets if s['name'] == name), None)
        if existing and not messagebox.askyesno(
                "Save Set", f"Replace the existing set '{name}'?", parent=self):
            return
        if existing:
            existing['rows'] = rows
        else:
            sets.append({'name': name, 'rows': rows})
        config = self._config()
        if config is None:
            self._report_error("Save Set Failed",
                               "No configuration storage is available.")
            return
        config.set('forwards', 'sets', sets)
        self._refresh_sets()
        self.set_var.set(name)
        self._set_status(f"Saved forward set '{name}' ({len(rows)} rule(s))")

    def _apply_set(self):
        """Re-create every rule of the selected set through the add machinery."""
        name = self.set_var.get().strip()
        if not name:
            messagebox.showinfo(
                "Apply Set",
                "Select a saved set first, or save one from the current rules.",
                parent=self)
            return
        entry = next((s for s in self._load_sets() if s['name'] == name), None)
        if not entry:
            self._refresh_sets()
            messagebox.showinfo(
                "Apply Set", f"The saved set '{name}' no longer exists.",
                parent=self)
            return
        rows = entry['rows']
        device_id = self.device_id

        def task():
            failures = []
            for row in rows:
                try:
                    self.device_manager.add_forward(
                        device_id, row['local'], row['remote'],
                        reverse=row['type'] == 'reverse')
                except Exception as e:
                    failures.append(f"{row['local']} -> {row['remote']}: {e}")
            self.after(0, lambda: self._on_set_applied(name, rows, failures))

        self._set_status(f"Applying {len(rows)} rule(s) from set '{name}'")
        threading.Thread(target=task, daemon=True).start()

    def _on_set_applied(self, name, rows, failures):
        if not self.winfo_exists():
            return
        applied = len(rows) - len(failures)
        if failures:
            self._report_error(
                "Apply Set Failed",
                f"Applied {applied} of {len(rows)} rule(s). "
                "Some could not be added:\n\n" + '\n'.join(failures))
        else:
            self._set_status(f"Applied set '{name}': {applied} rule(s)")
        self._refresh()

    def _delete_set(self):
        name = self.set_var.get().strip()
        if not name:
            messagebox.showinfo("Delete Set",
                                "Select the saved set to delete first.", parent=self)
            return
        if not messagebox.askyesno("Delete Set", f"Delete the saved set '{name}'?",
                                   parent=self):
            return
        config = self._config()
        if config is None:
            self._report_error("Delete Set Failed",
                               "No configuration storage is available.")
            return
        sets = [s for s in self._load_sets() if s['name'] != name]
        config.set('forwards', 'sets', sets)
        self._refresh_sets()
        self._set_status(f"Deleted forward set '{name}'")

    # -- loading -------------------------------------------------------

    def _refresh(self):
        """Read both forward lists from the adb server, then fill the tree."""
        if self._busy:
            return
        self._busy = True
        self._set_busy(True)

        def task():
            forwards, error = [], ''
            try:
                forwards = self.device_manager.list_forwards(reverse=False)
                reverses = self.device_manager.list_forwards(reverse=True)
            except Exception as e:
                error = str(e)
                reverses = []
            rows = ([dict(entry, direction=_SCOPE_FORWARD) for entry in forwards]
                    + [dict(entry, direction=_SCOPE_REVERSE) for entry in reverses])
            # Forwards cover every device; keep only this one.
            rows = [row for row in rows if row['serial'] == self.device_id]
            self.after(0, lambda: self._apply_forwards(rows, error))

        threading.Thread(target=task, daemon=True).start()

    def _apply_forwards(self, rows, error):
        self._busy = False
        if not self.winfo_exists():
            return

        self.tree.delete(*self.tree.get_children())
        self._entries = {}
        # The device's full rule list, kept for saving whole sets.
        self._all_rows = list(rows)

        scope = self.scope_var.get()
        for row in rows:
            if scope != _SCOPE_ALL and row['direction'] != scope:
                continue
            item = self.tree.insert('', tk.END,
                                    values=(row['direction'], row['local'], row['remote']))
            # Keyed by tree item id, which is what a selection reports.
            self._entries[item] = row

        forward_count = sum(1 for row in rows if row['direction'] == _SCOPE_FORWARD)
        reverse_count = len(rows) - forward_count
        self.summary_var.set(
            f"{forward_count} forward(s), {reverse_count} reverse(s) for {self.device_id}"
            + (f" - {error}" if error else ''))

    def _set_busy(self, busy):
        state = tk.DISABLED if busy else tk.NORMAL
        for button in (self.add_btn, self.remove_btn, self.remove_all_btn):
            button.configure(state=state)

    # -- actions -------------------------------------------------------

    def _selected_entries(self):
        return [self._entries[item] for item in self.tree.selection() if item in self._entries]

    def _add_forward(self):
        """Create a forward from the two endpoint fields."""
        local = self.local_var.get().strip()
        remote = self.remote_var.get().strip()
        if not local or not remote:
            messagebox.showinfo("Port Forwarding",
                                "Enter both a local and a remote endpoint, for example tcp:8080.",
                                parent=self)
            return
        if ':' not in local or ':' not in remote:
            messagebox.showinfo(
                "Port Forwarding",
                "Endpoints must look like 'tcp:8080'.\n"
                "Other kinds are localabstract:name, localreserved:name and jdwp:pid.",
                parent=self)
            return

        reverse = self.direction_var.get() == _SCOPE_REVERSE
        device_id = self.device_id

        def task():
            try:
                self.device_manager.add_forward(device_id, local, remote, reverse=reverse)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._report_error("Add Forward Failed", msg))
                return
            self.after(0, self._on_forward_added)

        self._set_status(f"Adding {'reverse ' if reverse else ''}forward {local} -> {remote}")
        threading.Thread(target=task, daemon=True).start()

    def _report_error(self, title, message):
        """Show a failure, unless the dialog was closed while adb was working."""
        if not self.winfo_exists():
            return
        messagebox.showerror(title, message, parent=self)

    def _on_forward_added(self):
        self._set_status("Forward added")
        self._refresh()

    def _remove_selected(self):
        """Remove every forward selected in the list."""
        selected = self._selected_entries()
        if not selected:
            messagebox.showinfo("Port Forwarding", "Select one or more forwards to remove.",
                                parent=self)
            return

        labels = '\n'.join(f"  {entry['direction']}  {entry['local']} -> {entry['remote']}"
                           for entry in selected)
        if not messagebox.askyesno("Remove Forward",
                                   "Remove these forwards?\n\n"
                                   f"{labels}\n\n"
                                   "Anything listening on those ports loses its connection.",
                                   parent=self):
            return

        device_id = self.device_id

        def task():
            failures = []
            for entry in selected:
                try:
                    self.device_manager.remove_forward(
                        device_id, entry['local'],
                        reverse=entry['direction'] == _SCOPE_REVERSE)
                except Exception as e:
                    failures.append(f"{entry['local']}: {e}")
            self.after(0, lambda: self._on_forwards_removed(selected, failures))

        threading.Thread(target=task, daemon=True).start()

    def _remove_all(self):
        """Clear the forwards covered by the current scope filter."""
        scope = self.scope_var.get()
        if not self._entries:
            messagebox.showinfo("Port Forwarding", "There is nothing to remove.", parent=self)
            return

        if scope == _SCOPE_ALL:
            message = "Remove every forward and reverse forward for this device?"
        else:
            message = f"Remove all {scope.lower()}s for this device?"
        if not messagebox.askyesno(
                "Remove All Forwards",
                message + "\n\nAnything listening on those ports loses its connection.",
                parent=self):
            return

        device_id = self.device_id
        directions = (False, True) if scope == _SCOPE_ALL else (scope == _SCOPE_REVERSE,)

        def task():
            failures = []
            for reverse in directions:
                try:
                    self.device_manager.remove_all_forwards(device_id, reverse=reverse)
                except Exception as e:
                    failures.append(f"{'reverse' if reverse else 'forward'}: {e}")
            self.after(0, lambda: self._on_forwards_removed([], failures))

        threading.Thread(target=task, daemon=True).start()

    def _on_forwards_removed(self, removed, failures):
        if not self.winfo_exists():
            return
        count = len(removed)
        if failures:
            self._report_error(
                "Remove Forward Failed",
                "Some forwards could not be removed:\n\n" + '\n'.join(failures))
        elif count:
            self._set_status(f"Removed {count} forward(s)")
        self._refresh()