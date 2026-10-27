"""Error dialog with a scrollable detail box plus Copy and Close buttons.

Used everywhere a command can fail with more output than fits in one
messagebox line: validation problems, command output, stderr, and so on.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


class ErrorDetailDialog(tk.Toplevel):
    def __init__(self, parent, title: str, message: str, details: str = ''):
        super().__init__(parent)
        self.title(title)
        self.geometry("430x180" if not details else "470x360")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=message, font=('', 9, 'bold'),
                  wraplength=430, justify='left').pack(anchor='w', pady=(0, 10))

        self._copy_btn = None
        self._details_text = ''
        if details:
            self._details_text = details
            box = ttk.Frame(frame)
            box.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

            self._details = tk.Text(box, height=9, wrap='word', font=('Consolas', 9),
                                    state=tk.DISABLED)
            self._details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(box, orient=tk.VERTICAL,
                                      command=self._details.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self._details.config(yscrollcommand=scrollbar.set)

            self._details.config(state=tk.NORMAL)
            self._details.insert('1.0', details)
            self._details.config(state=tk.DISABLED)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=2)
        if self._details_text:
            self._copy_btn = ttk.Button(buttons, text="Copy",
                                        command=self._copy_details)
            self._copy_btn.pack(side=tk.RIGHT, padx=2)

        setup_window_dpi(self, base_width=470 if details else 430,
                         base_height=360 if details else 180,
                         min_width=420, min_height=170, parent=parent)
        if details:
            self.resizable(True, True)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()

    def _copy_details(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self._details_text)
            self._copy_btn.config(text="Copied", state=tk.DISABLED)
            self.after(1500, self._restore_copy_button)
        except tk.TclError:
            pass

    def _restore_copy_button(self):
        try:
            self._copy_btn.config(text="Copy", state=tk.NORMAL)
        except tk.TclError:
            pass
