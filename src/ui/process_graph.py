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

INTERVALS = (1, 2, 3, 5, 10)
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


class ProcessHistoryWindow(tk.Toplevel):
    """The process list on the left, the history of the selection on the right."""

    def __init__(self, parent, device_id, device_manager):
        super().__init__(parent)
        self.title(f'Process History - {device_id}')
        self.device_id = device_id
        self.device_manager = device_manager

        self._series = {}
        self._keys = {}
        self._latest = {}
        self.selected_key = DEVICE_KEY
        self._sampling = False
        self._paused = False
        self._timer = None
        self._closing = False
        self._samples_taken = 0
        self._total_memory = 0

        self.interval_var = tk.IntVar(value=3)
        self.history_var = tk.IntVar(value=5)
        self.top_var = tk.IntVar(value=50)

        setup_window_dpi(self, base_width=1000, base_height=600,
                         min_width=700, min_height=420)
        self.transient(parent)

        self._create_widgets()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        # The window can also disappear without being closed, when the main
        # window takes its children down with it, so the timer is stopped from
        # both directions.
        self.bind('<Destroy>', self._on_destroy)
        self._take_sample()

    # --- layout ------------------------------------------------------------

    def _create_widgets(self):
        toolbar = ttk.Frame(self, padding=(10, 8, 10, 0))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text='Interval').pack(side=tk.LEFT)
        ttk.Combobox(toolbar, textvariable=self.interval_var, values=list(INTERVALS),
                     width=5, state='readonly').pack(side=tk.LEFT, padx=(6, 14))
        ttk.Label(toolbar, text='History').pack(side=tk.LEFT)
        ttk.Combobox(toolbar, textvariable=self.history_var,
                     values=list(HISTORY_CHOICES), width=5,
                     state='readonly').pack(side=tk.LEFT, padx=(6, 14))
        ttk.Label(toolbar, text='Show').pack(side=tk.LEFT)
        ttk.Combobox(toolbar, textvariable=self.top_var, values=list(TOP_CHOICES),
                     width=6, state='readonly').pack(side=tk.LEFT, padx=(6, 14))

        self.pause_button = ttk.Button(toolbar, text='Pause', width=9,
                                       command=self._toggle_pause)
        self.pause_button.pack(side=tk.LEFT)
        ttk.Button(toolbar, text='Clear', width=9, command=self._clear).pack(
            side=tk.LEFT, padx=8)
        self.sample_label = ttk.Label(toolbar, text='', foreground='gray')
        self.sample_label.pack(side=tk.RIGHT)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = ttk.Frame(panes, padding=(0, 0, 6, 0))
        right = ttk.Frame(panes, padding=(6, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        self._create_list(left)
        self._create_graph(right)

    def _create_list(self, parent):
        columns = ('CPU%', 'Memory', 'PID')
        self.tree = ttk.Treeview(parent, columns=columns, show='tree headings',
                                 selectmode='browse')
        self.tree.heading('#0', text='Process')
        for column in columns:
            self.tree.heading(column, text=column)
        self.tree.column('#0', width=scale_size(230, self), stretch=True)
        self.tree.column('CPU%', width=scale_size(80, self), anchor='e')
        self.tree.column('Memory', width=scale_size(90, self), anchor='e')
        self.tree.column('PID', width=scale_size(80, self), anchor='e')

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

    def _create_graph(self, parent):
        self.title_label = tk.Label(parent, text='Device totals', anchor=tk.W,
                                    font=('Segoe UI', 13, 'bold'))
        self.title_label.pack(fill=tk.X)

        values = ttk.Frame(parent)
        values.pack(fill=tk.X, pady=(8, 4))

        self.cpu_value = tk.Label(values, text='-', background=VALUE_CPU_BACKGROUND,
                                  foreground='#12395e', font=('Segoe UI', 20, 'bold'),
                                  padx=16, pady=8, width=11, anchor='center')
        self.cpu_value.pack(side=tk.LEFT)
        self.memory_value = tk.Label(values, text='-', background=VALUE_MEMORY_BACKGROUND,
                                     foreground='#7a4a10', font=('Segoe UI', 20, 'bold'),
                                     padx=16, pady=8, width=11, anchor='center')
        self.memory_value.pack(side=tk.LEFT, padx=(10, 0))

        self.stats_label = ttk.Label(parent, text='', foreground='gray', anchor=tk.W)
        self.stats_label.pack(fill=tk.X, pady=(0, 6))

        self.chart = HistoryChart(parent)
        self.chart.pack(fill=tk.BOTH, expand=True)

    # --- sampling ----------------------------------------------------------

    def _interval_seconds(self):
        try:
            return max(1, int(self.interval_var.get()))
        except (TypeError, ValueError):
            return 3

    def _window_seconds(self):
        try:
            return max(1, int(self.history_var.get())) * 60
        except (TypeError, ValueError):
            return 300

    def _max_samples(self):
        return max(2, min(MAX_SAMPLES,
                          int(self._window_seconds() // self._interval_seconds())))

    def _take_sample(self):
        """Read the device once, then queue the next read after this one lands.

        The next timer starts from the end of the read rather than from the
        start, so a device slower than the chosen interval simply samples at
        its own pace instead of queueing work it cannot keep up with.
        """
        if self._closing or self._paused or self._sampling:
            return
        self._sampling = True
        self.sample_label.config(text='Reading...')

        device_id = self.device_id

        def task():
            try:
                sample = self.device_manager.sample_process_load(device_id)
            except Exception as exc:
                # Python deletes the name at the end of the except block, so the
                # text has to be taken out here rather than read by the callback
                # later, when it would raise NameError and stop sampling for good.
                message = str(exc)
                if not self._closing:
                    self.after(0, lambda: self._on_sample_failed(message))
                return
            if not self._closing:
                self.after(0, lambda: self._on_sample(sample))

        threading.Thread(target=task, daemon=True).start()

    def _schedule_next(self):
        if self._closing or self._paused:
            return
        self._timer = self.after(self._interval_seconds() * 1000, self._take_sample)

    def _on_sample_failed(self, message):
        self._sampling = False
        self.sample_label.config(text=message, foreground='#C62828')
        self._schedule_next()

    def _on_sample(self, sample):
        self._sampling = False
        self._samples_taken += 1
        self.sample_label.config(
            text=f'{self._samples_taken} samples', foreground='gray')

        stamp = time.time()
        cpu_totals = sample.get('cpu') or {}
        memory_totals = sample.get('memory') or {}

        # The device row is the busiest share of all cores rather than any one
        # process, so it is not the sum of the rows below it.
        self._record(DEVICE_KEY, stamp, float(cpu_totals.get('busy') or 0.0),
                     int(memory_totals.get('used_bytes') or 0))

        processes = sample.get('processes') or []
        for process in processes:
            pid = str(process.get('pid') or '')
            if not pid:
                continue
            try:
                cpu = float(str(process.get('cpu', '0')).rstrip('%'))
            except (TypeError, ValueError):
                cpu = 0.0
            self._record(pid, stamp, cpu, _parse_size_bytes(process.get('mem')))

        self._trim()
        self._rebuild_list(processes, memory_totals)
        self._refresh_graph()
        self._schedule_next()

    def _record(self, key, stamp, cpu, memory):
        points = self._series.setdefault(key, [])
        points.append((stamp, cpu, memory))
        self._latest[key] = (cpu, memory)

    def _trim(self):
        """Drop points past the window, and series that ended before it."""
        limit = self._max_samples()
        for key, points in self._series.items():
            if len(points) > limit:
                del points[:len(points) - limit]

        window_start = self._series[DEVICE_KEY][0][0] if self._series.get(DEVICE_KEY) else 0
        for key in [key for key, points in self._series.items()
                    if key != DEVICE_KEY and points and points[-1][0] < window_start]:
            del self._series[key]
            self._latest.pop(key, None)

    # --- the list ----------------------------------------------------------

    def _rebuild_list(self, processes, memory_totals):
        """Rewrite the rows from the reading just taken, keeping the selection."""
        selected = self._keys.get(self.tree.selection()[0] if self.tree.selection() else '')

        for item in self.tree.get_children(''):
            self.tree.delete(item)
        self._keys.clear()

        device_cpu, device_memory = self._latest.get(DEVICE_KEY, (0.0, 0))
        device_item = self.tree.insert(
            '', tk.END, text='Device totals', open=True,
            values=(f'{device_cpu:.1f}%', _format_size(device_memory), ''))
        self._keys[device_item] = DEVICE_KEY
        self._total_memory = int(memory_totals.get('total_bytes') or 0)

        root = self.tree.insert('', tk.END, text='Processes', open=True)
        self._keys[root] = DEVICE_KEY

        try:
            limit = max(1, int(self.top_var.get()))
        except (TypeError, ValueError):
            limit = 50

        ordered = sorted(processes, key=lambda row: _row_cpu(row), reverse=True)[:limit]
        for process in ordered:
            pid = str(process.get('pid') or '')
            cpu, memory = self._latest.get(pid, (0.0, 0))
            item = self.tree.insert(
                root, tk.END, text=process.get('name') or pid,
                values=(f'{cpu:.1f}%', _format_size(memory), pid))
            self._keys[item] = pid

        target = None
        if selected:
            for item, key in self._keys.items():
                if key == selected:
                    target = item
                    break
        if target is None:
            target = device_item
            self.selected_key = DEVICE_KEY
        self.tree.selection_set(target)
        self.tree.focus(target)

    def _on_select(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        key = self._keys.get(selection[0])
        if key is None:
            return
        self.selected_key = key
        self._refresh_graph()

    # --- the chart ---------------------------------------------------------

    def _refresh_graph(self):
        points = self._series.get(self.selected_key) or []
        self.chart.set_points(points, self._window_seconds())

        if self.selected_key == DEVICE_KEY:
            self.title_label.config(text=self._device_title())
        else:
            self.title_label.config(
                text=f'{self._selected_name()}  (pid {self.selected_key})')

        if not points:
            self.cpu_value.config(text='-')
            self.memory_value.config(text='-')
            self.stats_label.config(text='No samples for this process yet.')
            return

        cpu_now = points[-1][1]
        memory_now = points[-1][2]
        cpus = [point[1] for point in points]
        memories = [point[2] for point in points]

        self.cpu_value.config(text=f'{cpu_now:.1f}%')
        self.memory_value.config(text=_format_size(memory_now))

        self.stats_label.config(
            text=f'CPU  peak {max(cpus):.1f}%  average {sum(cpus) / len(cpus):.1f}%   |   '
                 f'Memory  peak {_format_size(max(memories))}  '
                 f'average {_format_size(sum(memories) / len(memories))}   |   '
                 f'{len(points)} samples over {self._elapsed_span(points)}')

    def _elapsed_span(self, points):
        seconds = max(0.0, points[-1][0] - points[0][0])
        if seconds < 90:
            return f'{seconds:.0f}s'
        return f'{seconds / 60:.1f} min'

    def _device_title(self):
        """The device heading, with the in-use total only once one is known."""
        points = self._series.get(DEVICE_KEY) or []
        if not points or not self._total_memory:
            return 'Device totals'
        return (f'Device totals   {_format_size(points[-1][2])} of '
                f'{_format_size(self._total_memory)} in use')

    def _selected_name(self):
        """The name shown against the selection, wherever it sits in the tree."""
        stack = list(self.tree.get_children(''))
        while stack:
            item = stack.pop(0)
            if self._keys.get(item) == self.selected_key:
                text = self.tree.item(item, 'text')
                if text not in ('Device totals', 'Processes'):
                    return text
            stack.extend(self.tree.get_children(item))
        return f'pid {self.selected_key}'

    # --- controls ----------------------------------------------------------

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            if self._timer is not None:
                try:
                    self.after_cancel(self._timer)
                except Exception:
                    pass
                self._timer = None
            self.pause_button.config(text='Resume')
            self.sample_label.config(text='Paused', foreground='#E65100')
        else:
            self.pause_button.config(text='Pause')
            self._take_sample()

    def _clear(self):
        self._series.clear()
        self._latest.clear()
        self._samples_taken = 0
        for item in self.tree.get_children(''):
            self.tree.delete(item)
        self._keys.clear()
        self.selected_key = DEVICE_KEY
        self._refresh_graph()

    def set_device(self, device_id):
        """Point the window at another device, dropping the history of the old one."""
        self.device_id = device_id
        self.title(f'Process History - {device_id}')
        self._paused = False
        self.pause_button.config(text='Pause')
        self._clear()
        self._take_sample()

    def _stop_timer(self):
        self._closing = True
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    def _on_destroy(self, event):
        if event.widget is self:
            self._stop_timer()

    def _on_close(self):
        self._stop_timer()
        self.destroy()


def _row_cpu(process):
    try:
        return float(str(process.get('cpu', '0')).rstrip('%'))
    except (TypeError, ValueError):
        return 0.0