"""Confirm-options dialog in front of an APK install.

One dialog carries the old confirm's job (what gets installed where, the file
sizes, the large-file note) and adds the pm switches the install will run
with: replace, downgrade, test-only, and the root-only grant-everything
toggle. Closing it returns the chosen switches as a dict, or None on cancel.
"""

import tkinter as tk
from tkinter import ttk


class APKInstallOptionsDialog(tk.Toplevel):
    def __init__(self, parent, device_id: str, entries, big_note: str = ''):
        """Build the dialog.

        Args:
            entries: (label, size_mb) tuples, one per APK or APK set
            big_note: extra note about split bundles or large files
        """
        super().__init__(parent)
        self.title("Confirm Installation")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        listed = '\n'.join(f"  - {label} ({size_mb:.1f} MB)"
                           for label, size_mb in entries[:10])
        if len(entries) > 10:
            listed += f"\n  ... and {len(entries) - 10} more"

        ttk.Label(frame,
                  text=f"Install on device '{device_id}':\n\n{listed}",
                  wraplength=520, justify='left',
                  font=('', 9)).pack(anchor='w')

        options = ttk.LabelFrame(frame, text=" Options ", padding=10)
        options.pack(fill=tk.X, pady=(14, 4))

        self._vars = {
            'replace': tk.BooleanVar(self, True),
            'allow_downgrade': tk.BooleanVar(self, False),
            'test_only': tk.BooleanVar(self, False),
            'grant_all': tk.BooleanVar(self, False),
        }
        labels = (
            ('replace', 'Replace the app if it is already installed  (-r)'),
            ('allow_downgrade', 'Allow installing an older version  (-d)'),
            ('test_only', 'Install as a test-only package  (-t)'),
            ('grant_all', 'Grant all runtime permissions afterwards (needs root)'),
        )
        for key, text in labels:
            ttk.Checkbutton(options, text=text, variable=self._vars[key]).pack(
                anchor='w', pady=2)
        ttk.Label(options, wraplength=500, justify='left',
                  text=("Grant-all runs 'su -c pm grant' for each requested "
                        "permission and reports what it could not set."),
                  font=('', 8, 'italic')).pack(anchor='w', pady=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))
        install_btn = ttk.Button(buttons, text="Install", command=self._install,
                                 width=12)
        install_btn.pack(side=tk.RIGHT, padx=2)
        ttk.Button(buttons, text="Cancel", command=self.destroy,
                   width=10).pack(side=tk.RIGHT, padx=2)

        if big_note:
            ttk.Label(frame, text=big_note, wraplength=500, justify='left',
                      font=('', 9)).pack(anchor='w', pady=(10, 0))

        self.grab_set()
        self.bind('<Escape>', lambda event: self.destroy())
        install_btn.focus_set()

    def _install(self):
        self.result = {key: var.get() for key, var in self._vars.items()}
        self.destroy()
