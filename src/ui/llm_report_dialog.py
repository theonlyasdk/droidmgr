"""LLM Report Dialog and Progress Dialog for droidmgr."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional, Callable


class LLMReportProgressDialog(tk.Toplevel):
    """Progress dialog shown while gathering device information for LLM report."""

    def __init__(self, parent, title: str = "Generating LLM Report"):
        super().__init__(parent)
        self.title(title)
        self.geometry("520x130")
        self.resizable(False, False)
        self.transient(parent)

        self.cancelled = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._create_widgets()

        # Center window relative to parent
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (520 // 2)
            py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (130 // 2)
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())

    def _create_widgets(self):

        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.label = ttk.Label(
            main_frame,
            text="Initializing report generation...",
            font=('Arial', 10)
        )
        self.label.pack(anchor=tk.W, pady=(0, 12))

        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, expand=True)

        self.progressbar = ttk.Progressbar(
            progress_frame,
            orient='horizontal',
            mode='determinate',
            maximum=100
        )
        self.progressbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.pct_label = ttk.Label(
            progress_frame,
            text="0%",
            font=('Arial', 10, 'bold'),
            width=5,
            anchor=tk.E
        )
        self.pct_label.pack(side=tk.RIGHT)

    def update_progress(self, percent: int, text: str):
        """Update progress bar and status text safely from Tk main thread."""
        if not self.winfo_exists() or self.cancelled:
            return
        self.label.config(text=text)
        self.progressbar['value'] = percent
        self.pct_label.config(text=f"{int(percent)}%")
        self.update_idletasks()

    def _on_close(self):
        self.cancelled = True
        self.destroy()


class LLMReportDialog(tk.Toplevel):
    """Dialog displaying the generated single-paragraph LLM report."""

    def __init__(self, parent, device_id: str, report_text: str):
        super().__init__(parent)
        self.title(f"LLM Device Report - {device_id}")
        self.geometry("750x500")
        self.minsize(500, 350)
        self.transient(parent)

        self.report_text = report_text
        self._create_widgets()

        # Center window relative to parent
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (750 // 2)
            py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (500 // 2)
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda e: self.destroy())


    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 8))

        title_label = tk.Label(
            header_frame,
            text="Device Report for LLM Analysis",
            font=('Arial', 12, 'bold'),
            fg='#2196F3'
        )
        title_label.pack(side=tk.LEFT)

        # Text box for single paragraph report
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.text_widget = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            padx=8,
            pady=8
        )
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)

        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_widget.insert('1.0', self.report_text)

        # Bottom buttons: [Copy Report] [Close]
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = ttk.Label(btn_frame, text="", font=('Arial', 9, 'bold'))
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.close_btn = ttk.Button(
            btn_frame,
            text="Close",
            command=self.destroy,
            width=12
        )
        self.close_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.copy_btn = ttk.Button(
            btn_frame,
            text="Copy Report",
            command=self._copy_report,
            width=14
        )
        self.copy_btn.pack(side=tk.RIGHT, padx=5)

    def _copy_report(self):
        self.clipboard_clear()
        self.clipboard_append(self.report_text)
        self.status_label.config(text="Report has been copied to clipboard!", foreground="green")
        self.copy_btn.config(text="Copied!")
        self.after(2000, self._reset_copy_btn)

    def _reset_copy_btn(self):
        if self.winfo_exists():
            self.copy_btn.config(text="Copy Report")
            self.status_label.config(text="")
