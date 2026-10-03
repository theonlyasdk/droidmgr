"""Floating tooltip widget for the scrcpy overlay toolbar."""

import tkinter as tk


class _Tooltip:
    """Lightweight tooltip widget that floats to the left of the vertical toolbar."""

    def __init__(self, widget, text: str, side: str = "left"):
        self.widget = widget
        self.text = text
        self.side = side
        self.tip_window = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip_window or not self.text:
            return
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#252526", foreground="#e0e0e0",
            relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 9), padx=8, pady=4
        )
        label.pack()
        tw.update_idletasks()

        tw_w = tw.winfo_reqwidth()
        tw_h = tw.winfo_reqheight()

        if self.side == "left":
            x = self.widget.winfo_rootx() - tw_w - 6
            y = self.widget.winfo_rooty() + (self.widget.winfo_height() - tw_h) // 2
        else:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
            y = self.widget.winfo_rooty() + (self.widget.winfo_height() - tw_h) // 2

        if x < 0:
            x = 10
        if y < 0:
            y = 10
        tw.geometry(f"+{x}+{y}")

    def hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
