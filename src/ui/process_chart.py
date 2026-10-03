"""Process history graph, laid out the way a Windows task manager lays it out.

The process list sits on the left and the history of whatever is selected in it
is drawn on the right. Everything on the graph comes from repeated runs of the
same 'top' command the process tab already uses: the per-process CPU and memory
figures from the table, and the device's own totals from the summary lines
above it.

The chart is drawn straight onto a Canvas. A plotting library would bring its
own axes, legends and interaction to replace, and the whole of it is two lines
and a fill.
"""

import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from .dpi import setup_window_dpi, scale_size

# Key for the device-wide series, which is not a process and has no pid.
DEVICE_KEY = 'device'

# How the chart is coloured. Two flat colours read more clearly than a shaded
# area each, and the CPU fill is what makes a spike in it obvious at a glance.
CHART_BACKGROUND = '#ffffff'

CHART_GRID = '#e6eaee'

CHART_AXIS_TEXT = '#5b6670'

CPU_LINE = '#2f6fb5'

CPU_FILL = '#b7d2ee'

MEMORY_LINE = '#d98324'

VALUE_CPU_BACKGROUND = '#e8f0f9'

VALUE_MEMORY_BACKGROUND = '#fdf1e2'

# Longest history worth keeping, however it was asked for. Beyond this the
# points cost more memory than the extra resolution is worth.
MAX_SAMPLES = 1200

_SIZE_UNITS = {'B': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}

_SIZE_PATTERN = re.compile(r'([\d.]+)\s*([KMGT]?)B?\s*$', re.IGNORECASE)

INTERVALS = (0.5, 1, 2, 3, 5, 10)

HISTORY_CHOICES = (2, 5, 10, 20)

TOP_CHOICES = (25, 50, 100, 200)


def _parse_size_bytes(text):
    """'245.3 MB', '3.4M' or '0 KB' as a byte count."""
    match = _SIZE_PATTERN.match(str(text or '').strip())
    if not match:
        return 0
    unit = (match.group(2) or 'B').upper()
    return int(float(match.group(1)) * _SIZE_UNITS.get(unit, 1))

def _format_size(num_bytes):
    """A byte count as '245.3 MB'."""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{int(size)} B' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} GB'

def _nice_ceiling(value):
    """Round a peak up to a number an axis can be labelled with."""
    value = float(value or 0)
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1.0, 1.25, 2.0, 2.5, 4.0, 5.0, 10.0):
        candidate = step * magnitude
        if candidate >= value:
            return candidate
    return 10.0 * magnitude

def _row_cpu(process):
    try:
        return float(str(process.get('cpu', '0')).rstrip('%'))
    except (TypeError, ValueError):
        return 0.0


class HistoryChart(tk.Canvas):
    """A chart of CPU and memory over time, drawn onto itself.

    It holds the points it was last given so that a resize can redraw from them
    without asking the window for anything.
    """

    def __init__(self, parent):
        super().__init__(parent, background=CHART_BACKGROUND, highlightthickness=1,
                         highlightbackground='#c8d0d8')
        self.points = []
        self.window_seconds = 300.0
        self.bind('<Configure>', lambda event: self.redraw())

    def set_points(self, points, window_seconds):
        self.points = list(points)
        self.window_seconds = max(1.0, float(window_seconds or 0))
        self.redraw()

    def redraw(self):
        """Draw the whole chart: grid, both scales, both series and the labels."""
        self.delete('all')

        width = self.winfo_width()
        height = self.winfo_height()
        if width < 80 or height < 60:
            return

        left = 58
        right = width - 66
        top = 14
        bottom = height - 28
        if right <= left or bottom <= top:
            return
        plot_width = right - left
        plot_height = bottom - top

        newest = self.points[-1][0] if self.points else time.time()
        visible = [point for point in self.points
                   if point[0] >= newest - self.window_seconds]

        # The scales follow what is on screen rather than the whole buffer. A
        # peak that has already scrolled off would otherwise keep its ceiling and
        # flatten everything drawn after it.
        cpu_top = _nice_ceiling(max([100.0] + [point[1] for point in visible]))
        memory_peak = max([0.0] + [point[2] for point in visible])
        memory_top = _nice_ceiling(memory_peak) if memory_peak > 0 else 1.0

        # Four steps give five lines, which is enough to read a level off the
        # graph without turning the plot into a table of numbers.
        for step in range(5):
            fraction = step / 4.0
            y = bottom - fraction * plot_height
            self.create_line(left, y, right, y, fill=CHART_GRID)
            cpu_value = cpu_top * fraction
            memory_value = memory_top * fraction
            self.create_text(left - 8, y, text=f'{cpu_value:g}%', anchor='e',
                             fill=CHART_AXIS_TEXT, font=('Segoe UI', 8))
            self.create_text(right + 8, y,
                             text=_format_size(memory_value) if memory_value else '0',
                             anchor='w', fill=CHART_AXIS_TEXT, font=('Segoe UI', 8))

        def place(stamp, value, ceiling):
            x = right - (newest - stamp) / self.window_seconds * plot_width
            y = bottom - min(1.0, max(0.0, value / ceiling)) * plot_height
            return max(left, min(right, x)), y

        if visible:
            cpu_points = [place(point[0], point[1], cpu_top) for point in visible]
            memory_points = [place(point[0], point[2], memory_top) for point in visible]

            if len(cpu_points) > 1:
                self.create_polygon(
                    cpu_points + [(cpu_points[-1][0], bottom), (cpu_points[0][0], bottom)],
                    fill=CPU_FILL, outline='')
                self.create_line(cpu_points, fill=CPU_LINE, width=2, smooth=False)
            if len(memory_points) > 1:
                self.create_line(memory_points, fill=MEMORY_LINE, width=2, smooth=False)

            for x, y in (cpu_points[-1], memory_points[-1]):
                self.create_oval(x - 3, y - 3, x + 3, y + 3, fill=CHART_BACKGROUND,
                                 outline=CHART_AXIS_TEXT)

            span = self.window_seconds
            self.create_text(right, bottom + 14, text='now', anchor='e',
                             fill=CHART_AXIS_TEXT, font=('Segoe UI', 8))
            if span >= 120:
                left_label = f'-{span / 60:.0f} min'
            else:
                left_label = f'-{span:.0f}s'
            self.create_text(left, bottom + 14, text=left_label, anchor='w',
                             fill=CHART_AXIS_TEXT, font=('Segoe UI', 8))
        else:
            self.create_text((left + right) / 2, (top + bottom) / 2,
                             text='Waiting for the first sample', fill=CHART_AXIS_TEXT,
                             font=('Segoe UI', 10))
