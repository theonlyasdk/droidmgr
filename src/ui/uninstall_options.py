"""Uninstall switch dialog.

The uninstall confirm already exists two dialogs deep (plain, then the
system-app warning). This one only collects how the uninstall runs:
keep the app data (`pm uninstall -k`) and remove it for every user
(`--user all`). Closing it returns {'keep_data', 'all_users'}, or None when
cancelled.
"""

import tkinter as tk
from tkinter import ttk


class UninstallOptionsDialog(tk.Toplevel):
    def __init__(self, parent, packages):
        super().__init__(parent)
        self.title("Uninstall Options")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        count = len(packages)
        if count == 1:
            what = f"application\n\n  - {packages[0]}"
        else:
            listed = '\n'.join(f"  - {pkg}" for pkg in packages[:10])
            if count > 10:
                listed += f"\n  ... and {count - 10} more"
            what = f"{count} applications\n\n{listed}"
        ttk.Label(frame, text=f"Uninstall {what}?\n\nChoose uninstall first"
                              f"; the safety checks follow.",
                  wraplength=480, justify='left',
                  font=('', 9)).pack(anchor='w')

        options = ttk.LabelFrame(frame, text=" Options ", padding=10)
        options.pack(fill=tk.X, pady=(14, 4))

        self._keep_data = tk.BooleanVar(self, False)
        self._all_users = tk.BooleanVar(self, False)
        ttk.Checkbutton(options,
                        text="Keep application data and cache  (pm uninstall -k)",
                        variable=self._keep_data).pack(anchor='w', pady=2)
        ttk.Checkbutton(options,
                        text="Uninstall for every device user  (--user all)",
                        variable=self._all_users).pack(anchor='w', pady=2)
        ttk.Label(options, wraplength=480, justify='left',
                  text="Keeping data removes the app from the launcher but leaves "
                       "its settings, logins and downloads on the device, so an "
                       "immediate reinstall lands back with them.",
                  font=('', 8, 'italic')).pack(anchor='w', pady=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))
        go_btn = ttk.Button(buttons, text="Uninstall", command=self._uninstall,
                            width=12)
        go_btn.pack(side=tk.RIGHT, padx=2)
        ttk.Button(buttons, text="Cancel", command=self.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

        self.grab_set()
        self.bind('<Escape>', lambda event: self.destroy())
        go_btn.focus_set()

    def _uninstall(self):
        self.result = {'keep_data': self._keep_data.get(),
                       'all_users': self._all_users.get()}
        self.destroy()
