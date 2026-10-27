import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import shutil
import tempfile

from .app_info_inspection import AppInspectionMixin
from .process_info_dialog import ProcessInfoDialog


class AppInfoDialog(AppInspectionMixin, tk.Toplevel):
    def __init__(self, parent, app_info, device_id=None, device_manager=None):
        super().__init__(parent)
        self.title(f"Application Info: {app_info.get('package', 'App')}")
        self.geometry("860x650")
        self.minsize(760, 540)
        self.resizable(True, True)
        self.transient(parent)
        
        self.app_info = app_info
        self.device_id = device_id
        self.device_manager = device_manager
        self.icon_path = None
        self._static_data = {}
        self._current_apk_path = None

        # Main notebook containing Overview and Details tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        self.overview_tab = ttk.Frame(self.notebook)
        self.details_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.details_tab, text="Details")

        self._build_overview_tab()
        self._build_details_tab()

        # Bottom Bar
        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(bottom_bar, text="Close", command=self.destroy, width=12).pack(side=tk.RIGHT)

        # Center dialog relative to parent window
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            dw = self.winfo_reqwidth()
            dh = self.winfo_reqheight()
            cx = px + (pw // 2) - (dw // 2)
            cy = py + (ph // 2) - (dh // 2)
            self.geometry(f"+{max(0, cx)}+{max(0, cy)}")
        except Exception:
            pass
            
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())

        # Load icon asynchronously
        if self.device_id and self.device_manager:
            threading.Thread(target=self._load_icon_async, daemon=True).start()
            threading.Thread(target=self._load_static_apk_async, daemon=True).start()
        else:
            self.icon_label.config(text="No Device Link")
            self.static_status_lbl.config(text="No device link. Open a local APK to inspect.")

    def _build_overview_tab(self):
        frame = tk.Frame(self.overview_tab, padx=15, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        # 1. Right-side icon frame
        icon_frame = tk.Frame(frame, padx=10)
        icon_frame.pack(side=tk.RIGHT, fill=tk.Y, anchor='n')

        icon_area = tk.Frame(icon_frame, width=320, height=320, bg="#f0f0f0", bd=1, relief=tk.SUNKEN)
        icon_area.pack_propagate(False)
        icon_area.pack(pady=10)

        self.icon_label = tk.Label(icon_area, text="Loading icon...", bg="#f0f0f0", font=('', 11, 'bold'))
        self.icon_label.pack(fill=tk.BOTH, expand=True)

        default_icon = self._get_default_icon_path()
        if default_icon:
            self._update_icon_ui(default_icon)

        self.icon_menu = tk.Menu(self, tearoff=0)
        self.icon_menu.add_command(label="Save App Icon...", command=self._save_app_icon)
        self.icon_label.bind("<Button-3>", self._show_icon_context_menu)
        icon_area.bind("<Button-3>", self._show_icon_context_menu)

        icon_meta_frame = tk.Frame(icon_frame)
        icon_meta_frame.pack(fill=tk.X)
        ttk.Label(icon_meta_frame, text="App Icon", font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT)
        self.save_icon_btn = ttk.Button(icon_meta_frame, text="Save Icon...", command=self._save_app_icon, width=12)
        self.save_icon_btn.pack(side=tk.RIGHT)

        # 2. Left-side details frame
        details_frame = tk.Frame(frame)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 20))

        info_grid = tk.Frame(details_frame)
        info_grid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        info_grid.columnconfigure(1, weight=1)

        details = [
            ("Application Name:", self.app_info.get('name', self.app_info.get('package', ''))),
            ("Package Name:", self.app_info.get('package', '')),
            ("Version Name:", self.app_info.get('version_name', 'Unknown')),
            ("Version Code:", self.app_info.get('version_code', 'Unknown')),
            ("Install Time:", self.app_info.get('install_time', 'Unknown')),
            ("Update Time:", self.app_info.get('update_time', 'Unknown')),
            ("User ID:", self.app_info.get('user_id', 'Unknown')),
            ("Installer:", self.app_info.get('installer', 'Unknown')),
            ("Path:", self.app_info.get('path', 'Unknown')),
        ]

        for i, (label, value) in enumerate(details):
            ttk.Label(info_grid, text=label, font=('Segoe UI', 9, 'bold')).grid(row=i, column=0, sticky='nw', pady=4, padx=(0, 10))
            val_text = tk.Text(info_grid, height=1, width=38, wrap='char', bd=0, bg=frame.cget('bg'), font=('Segoe UI', 9))
            if len(str(value)) > 35:
                val_text.config(height=2)
            elif '\n' in str(value):
                val_text.config(height=str(value).count('\n') + 1)
            val_text.insert('1.0', str(value))
            val_text.config(state='disabled')
            val_text.grid(row=i, column=1, sticky='new', pady=4)

    def _build_details_tab(self):
        container = ttk.Frame(self.details_tab, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Top Action Bar
        top_bar = ttk.Frame(container)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        self.static_status_lbl = ttk.Label(top_bar, text="Ready to inspect APK", font=('Segoe UI', 9, 'italic'), foreground="#444444")
        self.static_status_lbl.pack(side=tk.LEFT)

        ttk.Button(top_bar, text="Inspect Local APK File...", command=self._browse_and_inspect_local_apk).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top_bar, text="Re-inspect", command=self._inspect_current_apk).pack(side=tk.RIGHT, padx=4)

        # Summary Metadata Card
        meta_card = ttk.LabelFrame(container, text=" APK & Build Metadata (No Install / AAPT)", padding=8)
        meta_card.pack(fill=tk.X, pady=(0, 8))
        meta_card.columnconfigure(1, weight=1)
        meta_card.columnconfigure(3, weight=1)

        ttk.Label(meta_card, text="Min / Target / Compile SDK:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky='w', pady=2)
        self.sdk_lbl = ttk.Label(meta_card, text="-", font=('Segoe UI', 9))
        self.sdk_lbl.grid(row=0, column=1, sticky='w', padx=6, pady=2)

        ttk.Label(meta_card, text="Debuggable:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=2, sticky='w', pady=2)
        self.debug_lbl = ttk.Label(meta_card, text="-", font=('Segoe UI', 9, 'bold'))
        self.debug_lbl.grid(row=0, column=3, sticky='w', padx=6, pady=2)

        ttk.Label(meta_card, text="Signatures:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, sticky='w', pady=2)
        self.sig_schemes_lbl = ttk.Label(meta_card, text="-", font=('Segoe UI', 9))
        self.sig_schemes_lbl.grid(row=1, column=1, sticky='w', padx=6, pady=2)

        ttk.Label(meta_card, text="Size & DEX:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=2, sticky='w', pady=2)
        self.size_dex_lbl = ttk.Label(meta_card, text="-", font=('Segoe UI', 9))
        self.size_dex_lbl.grid(row=1, column=3, sticky='w', padx=6, pady=2)

        # Fingerprint row
        ttk.Label(meta_card, text="SHA-256 Fingerprint:", font=('Segoe UI', 9, 'bold')).grid(row=2, column=0, sticky='w', pady=2)
        fp_frame = ttk.Frame(meta_card)
        fp_frame.grid(row=2, column=1, columnspan=3, sticky='ew', pady=2)
        self.sha256_entry = ttk.Entry(fp_frame, font=('Consolas', 8))
        self.sha256_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))
        ttk.Button(fp_frame, text="Copy", width=6, command=lambda: self._copy_to_clip(self.sha256_entry.get())).pack(side=tk.RIGHT)

        ttk.Label(meta_card, text="Signer Subject:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, sticky='w', pady=2)
        self.subject_lbl = ttk.Label(meta_card, text="-", font=('Segoe UI', 8))
        self.subject_lbl.grid(row=3, column=1, columnspan=3, sticky='w', padx=6, pady=2)

        # Components Sub-Notebook (Permissions, Activities, Services, Receivers & Providers)
        self.comp_notebook = ttk.Notebook(container)
        self.comp_notebook.pack(fill=tk.BOTH, expand=True)

        self.perm_tab = ttk.Frame(self.comp_notebook)
        self.act_tab = ttk.Frame(self.comp_notebook)
        self.srv_tab = ttk.Frame(self.comp_notebook)
        self.rec_tab = ttk.Frame(self.comp_notebook)

        self.comp_notebook.add(self.perm_tab, text="Permissions (0)")
        self.comp_notebook.add(self.act_tab, text="Activities (0)")
        self.comp_notebook.add(self.srv_tab, text="Services (0)")
        self.comp_notebook.add(self.rec_tab, text="Receivers & Providers (0)")

        self._build_component_view(self.perm_tab, 'perm')
        self._build_component_view(self.act_tab, 'act')
        self._build_component_view(self.srv_tab, 'srv')
        self._build_component_view(self.rec_tab, 'rec')

        # The runtime state lives on the device, so it is its own tab, filled
        # asynchronously next to the static APK inspection above.
        self.runtime_tab = ttk.Frame(self.comp_notebook)
        self.comp_notebook.add(self.runtime_tab, text="Runtime Permissions")
        self._build_runtime_permissions_view()

    def _build_component_view(self, parent_frame, kind):
        top = ttk.Frame(parent_frame, padding=4)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        search_var = tk.StringVar()
        setattr(self, f"{kind}_search_var", search_var)
        search_entry = ttk.Entry(top, textvariable=search_var, width=28)
        search_entry.pack(side=tk.LEFT, padx=4)

        tree_frame = ttk.Frame(parent_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        cols = ('name',)
        tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='browse')
        col_title = {
            'perm': 'Declared Permission',
            'act': 'Activity Class',
            'srv': 'Service Class',
            'rec': 'Receiver / Provider Class'
        }.get(kind, 'Component')
        tree.heading('name', text=col_title)
        tree.column('name', stretch=True)

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        setattr(self, f"{kind}_tree", tree)

        search_var.trace_add("write", lambda *_: self._filter_component_list(kind))

        btn_row = ttk.Frame(parent_frame, padding=4)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="Copy Selected", command=lambda: self._copy_selected_component(kind)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Copy All", command=lambda: self._copy_all_components(kind)).pack(side=tk.LEFT, padx=2)

    def _build_runtime_permissions_view(self):
        """The device-side runtime permission list with grant/revoke actions."""
        top = ttk.Frame(self.runtime_tab, padding=4)
        top.pack(fill=tk.X)

        self.runtime_status_lbl = ttk.Label(
            top, text="Loading device permissions...",
            font=('Segoe UI', 9, 'italic'), foreground="#444444")
        self.runtime_status_lbl.pack(side=tk.LEFT)

        self.runtime_grant_btn = ttk.Button(top, text="Grant", width=9,
                                            state=tk.DISABLED,
                                            command=self._grant_selected_permission)
        self.runtime_revoke_btn = ttk.Button(top, text="Revoke", width=9,
                                             state=tk.DISABLED,
                                             command=self._revoke_selected_permission)
        ttk.Button(top, text="Refresh", width=9,
                   command=self._reload_runtime_permissions).pack(side=tk.RIGHT,
                                                                  padx=2)
        self.runtime_revoke_btn.pack(side=tk.RIGHT, padx=2)
        self.runtime_grant_btn.pack(side=tk.RIGHT, padx=2)

        tree_frame = ttk.Frame(self.runtime_tab)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.runtime_tree = ttk.Treeview(tree_frame, columns=('perm', 'state'),
                                         show='headings', selectmode='browse')
        self.runtime_tree.heading('perm', text='Permission')
        self.runtime_tree.heading('state', text='Granted')
        self.runtime_tree.column('perm', stretch=True)
        self.runtime_tree.column('state', width=110, anchor='center', stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                               command=self.runtime_tree.yview)
        self.runtime_tree.configure(yscrollcommand=scroll.set)
        self.runtime_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.runtime_tree.tag_configure('granted', foreground='#2e7d32')
        self.runtime_tree.tag_configure('not_granted', foreground='#616161')
        self.runtime_tree.bind('<<TreeviewSelect>>', self._update_runtime_buttons)

        if self.device_id and self.device_manager:
            self._reload_runtime_permissions()
        else:
            self.runtime_status_lbl.config(
                text="No device link. Runtime permissions need a device.")

    def _reload_runtime_permissions(self):
        if not (self.device_id and self.device_manager):
            return
        self.runtime_status_lbl.config(text="Loading device permissions...")
        package = self.app_info.get('package', '')
        device_manager = self.device_manager
        device_id = self.device_id
        win = self

        def task():
            try:
                perms = device_manager.adb.get_runtime_permissions(device_id, package)
            except Exception as e:
                win.after(0, lambda: win._on_runtime_error(
                    f"Could not read runtime permissions: {e}"))
                return
            win.after(0, lambda: win._fill_runtime_permissions(perms))

        threading.Thread(target=task, daemon=True).start()

    def _fill_runtime_permissions(self, perms):
        self._runtime_perms = perms
        try:
            self.comp_notebook.tab(self.runtime_tab,
                                   text=f"Runtime Permissions ({len(perms)})")
            for item in self.runtime_tree.get_children():
                self.runtime_tree.delete(item)
            for name in sorted(perms):
                granted = perms[name]
                self.runtime_tree.insert(
                    '', tk.END, values=(name, 'yes' if granted else 'no'),
                    tags=('granted',) if granted else ('not_granted',))
            if perms:
                self.runtime_status_lbl.config(
                    text=f"{sum(perms.values())} of {len(perms)} granted")
            else:
                self.runtime_status_lbl.config(
                    text="No runtime permissions requested.")
            self._update_runtime_buttons()
        except tk.TclError:
            pass

    def _update_runtime_buttons(self, event=None):
        try:
            selected = self.runtime_tree.selection()
            state = tk.NORMAL if selected else tk.DISABLED
            self.runtime_grant_btn.config(state=state)
            self.runtime_revoke_btn.config(state=state)
        except tk.TclError:
            pass

    def _set_runtime_permission(self, action):
        """Run one grant/revoke on the device, then reload the list."""
        package = self.app_info.get('package', '')
        selected = self.runtime_tree.selection()
        if not selected:
            return
        permission = self.runtime_tree.item(selected[0], 'values')[0]
        device_manager = self.device_manager
        device_id = self.device_id
        win = self

        def task():
            try:
                getattr(device_manager.adb, f'{action}_permission')(
                    device_id, package, permission)
            except Exception as e:
                win.after(0, lambda: win._on_runtime_error(
                    f"{action.title()} failed: {e}"))
                return
            win.after(0, win._reload_runtime_permissions)

        self.runtime_status_lbl.config(
            text=f"{action.title()}ting {permission}...")
        threading.Thread(target=task, daemon=True).start()

    def _grant_selected_permission(self):
        self._set_runtime_permission('grant')

    def _revoke_selected_permission(self):
        self._set_runtime_permission('revoke')

    def _on_runtime_error(self, message):
        messagebox.showerror("Runtime Permission Error", message, parent=self)
        self.runtime_status_lbl.config(text="Reload to retry.")

    def _copy_to_clip(self, text):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _copy_selected_component(self, kind):
        tree = getattr(self, f"{kind}_tree")
        sel = tree.selection()
        if sel:
            val = tree.item(sel[0], 'values')[0]
            self._copy_to_clip(val)

    def _copy_all_components(self, kind):
        tree = getattr(self, f"{kind}_tree")
        items = [tree.item(i, 'values')[0] for i in tree.get_children()]
        if items:
            self._copy_to_clip('\n'.join(items))

    def _filter_component_list(self, kind):
        query = getattr(self, f"{kind}_search_var").get().lower().strip()
        tree = getattr(self, f"{kind}_tree")
        all_items = getattr(self, f"_{kind}_all", [])
        for item in tree.get_children():
            tree.delete(item)
        for val in all_items:
            if not query or query in val.lower():
                tree.insert('', tk.END, values=(val,))


__all__ = ['AppInfoDialog', 'ProcessInfoDialog']
