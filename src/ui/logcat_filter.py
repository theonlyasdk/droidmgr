"""Logcat level parsing and filter helpers."""
"""Split from logcat_view.py (MOVE-ONLY)."""

from collections import deque
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog

# brief format: "<PRIO>/<tag>(<pid>): <message>", e.g. "I/ActivityManager( 1234): Start proc"
_BRIEF_RE = re.compile(r'^([VDIWEFS])/(.+)$')

_LEVEL_ORDER = {'V': 0, 'D': 1, 'I': 2, 'W': 3, 'E': 4, 'F': 5, 'S': 6}

_LEVEL_LABELS = {
    'V': 'Verbose (V)',
    'D': 'Debug (D)',
    'I': 'Info (I)',
    'W': 'Warn (W)',
    'E': 'Error (E)',
}

MAX_BUFFER_LINES = 10000

MAX_RENDER_LINES = 2000


def parse_brief_level(line: str) -> str:
    """Extract the log level letter from a `logcat -v brief` line.

    Returns '' for header lines such as '--------- beginning of main'.
    """
    stripped = line.lstrip()
    if not stripped:
        return ''
    match = _BRIEF_RE.match(stripped)
    if match:
        return match.group(1)
    return ''

def level_passes(line_level: str, min_level: str) -> bool:
    """Check if a line level meets the minimum severity filter."""
    if not line_level:
        return True
    return _LEVEL_ORDER.get(line_level, -1) >= _LEVEL_ORDER.get(min_level, 0)


class LogcatFilterMixin:
    """Logcat level/search filtering."""

    # -- filtering helpers ----------------------------------------------
    def _current_min_level(self) -> str:
        for letter, label in _LEVEL_LABELS.items():
            if self.level_var.get() == label:
                return letter
        return 'V'

    def _line_visible(self, line: str, level: str) -> bool:
        if not level_passes(level, self._current_min_level()):
            return False
        needle = self.search_var.get().strip().lower()
        if needle and needle not in line.lower():
            return False
        return True

    def _on_search_changed(self):
        # Debounce rapid keystrokes via a short after() delay.
        if getattr(self, '_search_after_id', None):
            try:
                self.frame.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.frame.after(250, self._refilter)

    def _refilter(self):
        self._clear_view()
        with self.buffer_lock:
            snapshot = list(self.buffer)
        visible = [(line, level) for line, level in snapshot if self._line_visible(line, level)]
        to_render = visible[-MAX_RENDER_LINES:]
        self._append_lines_batch(to_render)
        self._update_status()
        if self.autoscroll.get() and to_render:
            try:
                self.log_text.see(tk.END)
            except Exception:
                pass
