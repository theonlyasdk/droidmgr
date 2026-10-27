"""Dialog for APK installs: busy state while installing, then the outcome.

One window covers the whole install. While ADB pushes and installs, it shows
an indeterminate progress bar; when the installs end, the same window reports
how long they took and lists failures in a scrollable, copyable text box.
"""

import tkinter as tk
from tkinter import ttk

from .dpi import setup_window_dpi


_BUSY_DETAIL = "Please wait while ADB pushes and installs the package."


def format_elapsed(seconds: float) -> str:
    """Render a duration as '<n.n> s', or '<n> m <ss> s' for longer runs."""
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(int(round(seconds)), 60)
    return f"{minutes} m {seconds:02d} s"


def _result_details(installed, failures, notes=()):
    """The report lines shown in the scrollable box: what installed, what failed."""
    lines = []
    if installed:
        lines.append("Installed:")
        lines.extend(f"  - {name}" for name in installed)
    if failures:
        if lines:
            lines.append("")
        lines.append("Failed:")
        lines.extend(f"  - {failure}" for failure in failures)
    for note in notes:
        if lines:
            lines.append("")
        lines.append(note)
    return "\n".join(lines)


class APKInstallProgressDialog(tk.Toplevel):
    def __init__(self, parent, filename: str, filesize_mb: float):
        super().__init__(parent)
        self._parent = parent
        self._details_text = None
        self._copy_btn = None

        self.title("Installing APK...")
        self.geometry("420x150")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        self._frame = frame

        self._header = ttk.Label(
            frame,
            text=f"Installing '{filename}' ({filesize_mb:.1f} MB)...",
            font=('', 10, 'bold'),
            wraplength=380
        )
        self._header.pack(anchor='w', pady=(0, 5))

        self._detail = ttk.Label(
            frame, text=_BUSY_DETAIL, font=('', 9), wraplength=380,
            justify='left')
        self._detail.pack(anchor='w', pady=(0, 15))

        self.progressbar = ttk.Progressbar(frame, mode='indeterminate')
        self.progressbar.pack(fill=tk.X, expand=True)
        self.progressbar.start(10)

        setup_window_dpi(self, base_width=420, base_height=150, parent=parent)

        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.grab_set()

    # -- result state ---------------------------------------------------

    def finish(self, elapsed_seconds: float, installed=None, failures=None,
               notes=None):
        """Replace the spinner with the install outcome, in the same window.

        Args:
            elapsed_seconds: How long the installs took, measured by the
                background thread.
            installed: Names of the APKs that installed successfully.
            failures: 'file: message' strings, one for each failed APK.
            notes: Extra outcome lines, e.g. grant-all results.
        """
        installed = installed or []
        failures = failures or []
        notes = notes or []
        duration = format_elapsed(elapsed_seconds)
        try:
            self.progressbar.stop()
            self.progressbar.pack_forget()

            if failures:
                self.title("Install Error")
                self._header.config(text="Installation finished with errors")
                if installed:
                    summary = (f"{len(installed)} installed, "
                               f"{len(failures)} failed in {duration}.")
                else:
                    summary = f"Installation failed after {duration}."
                self._detail.config(text=summary, foreground='dark red')
            else:
                self.title("Install Complete")
                self._header.config(text="Installation complete")
                if len(installed) > 1:
                    summary = f"{len(installed)} APKs installed in {duration}."
                else:
                    summary = f"APK installed successfully in {duration}."
                self._detail.config(text=summary)

            # Errors and several installed files go into the scrollable box;
            # a single clean install needs no report.
            if failures or len(installed) > 1 or notes:
                self._show_details_box(_result_details(installed, failures, notes))
                self._show_buttons(with_copy=bool(failures))
                setup_window_dpi(self, base_width=470, base_height=360,
                                 min_width=460, min_height=330,
                                 parent=self._parent)
                self.resizable(True, True)
            else:
                self._show_buttons(with_copy=False)
                setup_window_dpi(self, base_width=430, base_height=175,
                                 parent=self._parent)

            self.protocol("WM_DELETE_WINDOW", self.close)
        except tk.TclError:
            # The main window was closed while the install was running.
            pass

    def _show_details_box(self, text: str):
        self._details_text = text

        box = ttk.Frame(self._frame)
        box.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self._details = tk.Text(box, height=8, wrap='word', font=('', 9),
                                state=tk.DISABLED)
        self._details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(box, orient=tk.VERTICAL,
                                  command=self._details.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._details.config(yscrollcommand=scrollbar.set)

        self._details.config(state=tk.NORMAL)
        self._details.insert('1.0', text)
        self._details.config(state=tk.DISABLED)

    def _show_buttons(self, with_copy: bool):
        self._button_row = ttk.Frame(self._frame)
        self._button_row.pack(fill=tk.X, pady=(14, 0))

        close_btn = ttk.Button(self._button_row, text="Close", command=self.close)
        close_btn.pack(side=tk.RIGHT, padx=2)

        if with_copy:
            self._copy_btn = ttk.Button(self._button_row, text="Copy",
                                        command=self._copy_details)
            self._copy_btn.pack(side=tk.RIGHT, padx=2)

    def _copy_details(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self._details_text or "")
            self._copy_btn.config(text="Copied", state=tk.DISABLED)
            self.after(1500, self._restore_copy_button)
        except tk.TclError:
            pass

    def _restore_copy_button(self):
        try:
            self._copy_btn.config(text="Copy", state=tk.NORMAL)
        except tk.TclError:
            pass

    def close(self):
        try:
            self.progressbar.stop()
        except Exception:
            pass
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
