"""Bug report collection dialogs for droidmgr.

The progress window covers a collection that runs for minutes with nothing to
report until it lands, and the results window briefs the user on what was
collected and hands them the zip to keep.
"""

import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .dpi import setup_window_dpi, scale_size


class BugReportProgressDialog(tk.Toplevel):
    """Progress window shown while adb collects a bugreport.

    adb reports nothing structured until the report is complete, so the bar
    sweeps rather than filling and the only honest measure is the clock.
    """

    def __init__(self, parent, device_id: str):
        super().__init__(parent)
        self.title(f"Collecting Bug Report - {device_id}")
        self.resizable(False, False)
        self.transient(parent)
        self.device_id = device_id
        self.backgrounded = False
        self._started = None
        self._elapsed = 0.0
        self.protocol("WM_DELETE_WINDOW", self._on_background)

        self._create_widgets()
        setup_window_dpi(self, base_width=520, base_height=190, parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda event: self._on_background())

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.label = ttk.Label(
            main_frame,
            text=f"Collecting a bug report from {self.device_id}...",
            font=('Arial', 10),
            wraplength=scale_size(470, self),
            justify=tk.LEFT,
        )
        self.label.pack(anchor=tk.W, pady=(0, 10))

        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X)

        self.progressbar = ttk.Progressbar(
            progress_frame, orient='horizontal', mode='indeterminate'
        )
        self.progressbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.elapsed_label = ttk.Label(
            progress_frame, text="0s", font=('Arial', 10, 'bold'),
            width=7, anchor=tk.E
        )
        self.elapsed_label.pack(side=tk.RIGHT)

        note = ttk.Label(
            main_frame,
            text="This runs on the device and usually takes a few minutes. "
                 "Leaving this window open is fine; the report keeps being "
                 "collected either way.",
            font=('Arial', 9),
            wraplength=scale_size(470, self),
            justify=tk.LEFT,
        )
        note.pack(anchor=tk.W, pady=(12, 0))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(btn_frame, text="Continue in Background",
                   command=self._on_background).pack(side=tk.RIGHT)

    def start(self):
        """Begin sweeping the bar and counting the clock."""
        import time
        self._started = time.monotonic()
        self.progressbar.start(12)
        self._tick()

    def _tick(self):
        import time
        if not self.winfo_exists() or self._started is None:
            return
        self._elapsed = time.monotonic() - self._started
        minutes, seconds = divmod(int(self._elapsed), 60)
        self.elapsed_label.config(text=f"{minutes}m {seconds:02d}s")
        self.after(500, self._tick)

    def _on_background(self):
        """Step out of the way; the collection carries on without us."""
        self.backgrounded = True
        self.destroy()


class BugReportDialog(tk.Toplevel):
    """Briefing for a collected bugreport, with somewhere to put the zip."""

    def __init__(self, parent, device_id: str, zip_path: str, briefing: str):
        super().__init__(parent)
        self.title(f"Bug Report - {device_id}")
        self.transient(parent)
        self.device_id = device_id
        self.zip_path = zip_path
        self.briefing = briefing
        self.saved_to = ''

        self._create_widgets()
        setup_window_dpi(self, base_width=800, base_height=620,
                         min_width=560, min_height=400, parent=parent)
        self.wait_visibility()
        self.grab_set()
        self.bind('<Escape>', lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(header_frame, text="Bug Report Collected",
                 font=('Arial', 12, 'bold'), fg='#4CAF50').pack(side=tk.LEFT)
        ttk.Label(header_frame, text=self.device_id,
                  font=('Arial', 10)).pack(side=tk.LEFT, padx=(8, 0))

        try:
            size = os.path.getsize(self.zip_path)
        except OSError:
            size = 0
        self.archive_label = ttk.Label(
            main_frame,
            text=f"{os.path.basename(self.zip_path)}  ({size / 1024 / 1024:.1f} MB) "
                 f"held at {self.zip_path}",
            font=('Arial', 9), wraplength=scale_size(740, self), justify=tk.LEFT
        )
        self.archive_label.pack(anchor=tk.W, pady=(0, 8))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.text_widget = tk.Text(
            text_frame, wrap=tk.NONE, font=('Consolas', 10), padx=8, pady=8
        )
        self.text_widget.insert('1.0', self.briefing)
        self.text_widget.configure(state=tk.DISABLED)

        vertical = ttk.Scrollbar(text_frame, orient=tk.VERTICAL,
                                 command=self.text_widget.yview)
        horizontal = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL,
                                   command=self.text_widget.xview)
        self.text_widget.configure(yscrollcommand=vertical.set,
                                   xscrollcommand=horizontal.set)

        self.text_widget.grid(row=0, column=0, sticky=tk.NSEW)
        vertical.grid(row=0, column=1, sticky=tk.NS)
        horizontal.grid(row=1, column=0, sticky=tk.EW)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = ttk.Label(btn_frame, text="", font=('Arial', 9, 'bold'))
        self.status_label.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="Close", command=self._close,
                   width=12).pack(side=tk.RIGHT, padx=(5, 0))
        self.copy_btn = ttk.Button(btn_frame, text="Copy Briefing",
                                   command=self._copy_briefing, width=16)
        self.copy_btn.pack(side=tk.RIGHT, padx=5)
        self.save_as_btn = ttk.Button(btn_frame, text="Save As...",
                                      command=self._save_as, width=14)
        self.save_as_btn.pack(side=tk.RIGHT, padx=5)
        self.save_folder_btn = ttk.Button(
            btn_frame, text="Save to Folder...", command=self._save_to_folder,
            width=18)
        self.save_folder_btn.pack(side=tk.RIGHT, padx=5)

    def _copy_briefing(self):
        self.clipboard_clear()
        self.clipboard_append(self.briefing)
        self._set_status("Briefing copied to clipboard.", "green")
        self.copy_btn.config(text="Copied!")
        self.after(2000, self._reset_copy_btn)

    def _reset_copy_btn(self):
        if self.winfo_exists():
            self.copy_btn.config(text="Copy Briefing")
            self.status_label.config(text="")

    def _set_status(self, message, colour="green"):
        self.status_label.config(text=message, foreground=colour)

    def _save_as(self):
        """Pick an exact filename and put the zip there."""
        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="Save Bug Report As",
            defaultextension='.zip',
            initialfile=os.path.basename(self.zip_path),
            filetypes=[("Zip archive", "*.zip"), ("All files", "*.*")],
        )
        if not chosen:
            return
        if not chosen.lower().endswith('.zip'):
            chosen += '.zip'
        self._copy_to(chosen)

    def _save_to_folder(self):
        """Pick a folder and drop the zip into it under its own name."""
        chosen = filedialog.askdirectory(
            parent=self,
            title="Choose a folder for the bug report",
            mustexist=True,
        )
        if not chosen:
            return
        self._copy_to(os.path.join(chosen, os.path.basename(self.zip_path)))

    def _copy_to(self, target):
        try:
            if os.path.abspath(target) != os.path.abspath(self.zip_path):
                shutil.copy2(self.zip_path, target)
            self.saved_to = target
        except Exception as exc:
            self._set_status(f"Could not save: {exc}", "#D32F2F")
            messagebox.showerror("Save Failed", f"Could not write {target}\n\n{exc}",
                                 parent=self)
            return
        self._set_status(f"Saved to {target}")
        messagebox.showinfo(
            "Bug Report Saved",
            f"Saved to:\n{target}\n\n"
            f"A bugreport can contain personal data. Read it before sharing it.",
            parent=self)

    def _close(self):
        if self.saved_to:
            self.destroy()
            return
        if not os.path.isfile(self.zip_path):
            self.destroy()
            return
        # The working copy is the only copy until the user saves it somewhere.
        if messagebox.askyesno(
                "Close without saving?",
                f"The report has not been saved anywhere yet. It stays at:\n"
                f"{self.zip_path}\n\nClose anyway?",
                parent=self):
            self.destroy()