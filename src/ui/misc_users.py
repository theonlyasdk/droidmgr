"""Multi-user manager for the Developer Options tab."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk


class MiscUsersMixin:
    def _refresh_users(self):
        device_id = self.get_selected_device()
        if not device_id:
            for item in self.user_tree.get_children():
                self.user_tree.delete(item)
            return

        def bg_task():
            try:
                users = self.device_manager.adb.get_users(device_id)
                def update_ui():
                    if getattr(self, '_closing', False):
                        return
                    for item in self.user_tree.get_children():
                        self.user_tree.delete(item)
                    for u in users:
                        status_parts = []
                        if u.get('current'):
                            status_parts.append("ACTIVE / CURRENT")
                        elif u.get('running'):
                            status_parts.append("Running")
                        else:
                            status_parts.append("Stopped")
                        status_str = " | ".join(status_parts)
                        self.user_tree.insert('', tk.END, iid=u['id'], values=(u['id'], u['name'], status_str, u.get('flags', '')))
                self.after(0, update_ui)
            except Exception:
                pass

        threading.Thread(target=bg_task, daemon=True).start()

    def _switch_selected_user(self):
        sel = self.user_tree.selection()
        if not sel:
            messagebox.showinfo("Switch User", "Please select a user profile to switch to.", parent=self)
            return
        user_id = sel[0]
        device_id = self.get_selected_device()
        if not device_id:
            return

        self.status_lbl.config(text=f"Switching to user {user_id}...")
        def bg_task():
            ok, msg = self.device_manager.adb.switch_user(device_id, user_id)
            def update_ui():
                if ok:
                    self.set_status(f"Switched to user {user_id}")
                    self.status_lbl.config(text=f"Switched to user {user_id}")
                    self.after(1000, self._refresh_users)
                else:
                    messagebox.showerror("Switch User Failed", msg, parent=self)
            self.after(0, update_ui)
        threading.Thread(target=bg_task, daemon=True).start()

    def _show_create_user_dialog(self):
        device_id = self.get_selected_device()
        if not device_id:
            messagebox.showwarning("No Device", "Please select a connected device.", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Create User Profile")
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="User / Profile Name:").grid(row=0, column=0, sticky='w', pady=4)
        name_var = tk.StringVar(value="TestUser")
        ttk.Entry(frame, textvariable=name_var, width=24).grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(frame, text="Profile Type:").grid(row=1, column=0, sticky='w', pady=4)
        type_var = tk.StringVar(value="Standard User")
        type_combo = ttk.Combobox(frame, textvariable=type_var, values=["Standard User", "Guest", "Managed (Work Profile)"], state="readonly", width=22)
        type_combo.grid(row=1, column=1, sticky='w', padx=6, pady=4)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(12, 0), sticky='e')

        def on_create():
            u_name = name_var.get().strip()
            if not u_name:
                messagebox.showwarning("Empty Name", "Please enter a user name.", parent=dlg)
                return
            t_sel = type_var.get()
            u_type = 'standard'
            if 'Guest' in t_sel:
                u_type = 'guest'
            elif 'Work' in t_sel or 'Managed' in t_sel:
                u_type = 'managed'
            dlg.destroy()

            self.status_lbl.config(text=f"Creating user '{u_name}'...")
            def bg_task():
                ok, msg = self.device_manager.adb.create_user(device_id, u_name, u_type)
                def on_done():
                    if ok:
                        self.set_status(f"Created user: {u_name}")
                        self.status_lbl.config(text=f"Created user '{u_name}'")
                        self._refresh_users()
                    else:
                        messagebox.showerror("Create User Failed", msg, parent=self)
                self.after(0, on_done)
            threading.Thread(target=bg_task, daemon=True).start()

        ttk.Button(btn_row, text="Create", command=on_create).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

    def _remove_selected_user(self):
        sel = self.user_tree.selection()
        if not sel:
            messagebox.showinfo("Remove User", "Please select a user profile to remove.", parent=self)
            return
        user_id = sel[0]
        if str(user_id) == '0':
            messagebox.showwarning("Cannot Remove Owner", "User 0 is the primary device owner and cannot be removed.", parent=self)
            return

        device_id = self.get_selected_device()
        if not device_id:
            return

        if not messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove user {user_id} and all its data?", parent=self):
            return

        self.status_lbl.config(text=f"Removing user {user_id}...")
        def bg_task():
            ok, msg = self.device_manager.adb.remove_user(device_id, user_id)
            def update_ui():
                if ok:
                    self.set_status(f"Removed user {user_id}")
                    self.status_lbl.config(text=f"Removed user {user_id}")
                    self._refresh_users()
                else:
                    messagebox.showerror("Remove User Failed", msg, parent=self)
            self.after(0, update_ui)
        threading.Thread(target=bg_task, daemon=True).start()
