"""Choice after a successful fastboot flash: reboot, test-boot, or leave it.

Rebooting into Android and test-booting the image once (`fastboot boot <img>`,
nothing is written) are mutually exclusive ways to leave the bootloader, so
the plain "Reboot the device now?" question grows a third future: stay put.
The caller reads .chosen after construction; the dialog sets it from the
button press (or leaves None when the window is closed) and takes itself
down, releasing the grab.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi
from .apk_install_progress import format_elapsed


class PostFlashChoiceDialog(tk.Toplevel):
    """Small modal with the two post-flash futures plus 'do neither'."""

    def __init__(self, parent, image_name: str, partition: str, elapsed: float):
        super().__init__(parent)
        self.title('Flash Succeeded')
        self.resizable(False, False)
        self.transient(parent)

        self.chosen = None

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text=f"'{image_name}' was flashed to the {partition} "
                       f"partition in {format_elapsed(elapsed)}.",
                  font=('', 10, 'bold'), wraplength=380,
                  justify='left').pack(anchor='w', pady=(0, 8))

        ttk.Label(frame,
                  text="The device is still in the bootloader. Rebooting "
                       "starts Android. Test-booting runs the image once from "
                       "memory without writing anything, to see that it works "
                       "before committing to it.",
                  wraplength=380, justify='left').pack(anchor='w', pady=(0, 10))

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(buttons, text='Reboot Now',
                   command=self._pick_reboot).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text='Test-Boot This Image Once',
                   command=self._pick_testboot).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text='Leave It',
                   command=self._close).pack(side=tk.LEFT)

        setup_window_dpi(self, base_width=420, base_height=185,
                         min_width=380, min_height=150, parent=parent)
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.grab_set()
        self.focus_set()

    def _pick_reboot(self):
        self.chosen = 'reboot'
        self._close()

    def _pick_testboot(self):
        self.chosen = 'testboot'
        self._close()

    def _close(self):
        self.grab_release()
        self.destroy()
