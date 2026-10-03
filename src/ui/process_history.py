"""Process history sampling window (task-manager style graph)."""
"""Split from process_graph.py (MOVE-ONLY); re-exported via process_graph."""

import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from .dpi import setup_window_dpi, scale_size
from .process_chart import (
    DEVICE_KEY, MAX_SAMPLES, INTERVALS, HISTORY_CHOICES, TOP_CHOICES,
    CPU_LINE, MEMORY_LINE, VALUE_CPU_BACKGROUND, VALUE_MEMORY_BACKGROUND,
    HistoryChart, _format_size, _parse_size_bytes,
)
from .process_list import ProcessListMixin


class ProcessHistoryWindow(ProcessListMixin):
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

        self.interval_var = tk.StringVar(value='3')
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

    def _create_graph(self, parent):
        self.title_label = tk.Label(parent, text='Device totals', anchor=tk.W,
                                    font=('Segoe UI', 13, 'bold'))
        self.title_label.pack(fill=tk.X)

        values = ttk.Frame(parent)
        values.pack(fill=tk.X, pady=(8, 4))
        values.columnconfigure(0, weight=1, uniform='boxes')
        values.columnconfigure(1, weight=1, uniform='boxes')

        self.cpu_box = tk.Frame(values, background=VALUE_CPU_BACKGROUND, padx=16, pady=8)
        self.cpu_box.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        self.cpu_label = tk.Label(self.cpu_box, text='CPU', background=VALUE_CPU_BACKGROUND,
                                  foreground=CPU_LINE, font=('Segoe UI', 9, 'bold'),
                                  anchor='center')
        self.cpu_label.pack(fill=tk.X)
        self.cpu_value = tk.Label(self.cpu_box, text='-', background=VALUE_CPU_BACKGROUND,
                                  foreground='#12395e', font=('Segoe UI', 20, 'bold'),
                                  anchor='center')
        self.cpu_value.pack(fill=tk.X)

        self.memory_box = tk.Frame(values, background=VALUE_MEMORY_BACKGROUND, padx=16, pady=8)
        self.memory_box.grid(row=0, column=1, sticky='nsew', padx=(5, 0))
        self.memory_label = tk.Label(self.memory_box, text='Memory', background=VALUE_MEMORY_BACKGROUND,
                                     foreground=MEMORY_LINE, font=('Segoe UI', 9, 'bold'),
                                     anchor='center')
        self.memory_label.pack(fill=tk.X)
        self.memory_value = tk.Label(self.memory_box, text='-', background=VALUE_MEMORY_BACKGROUND,
                                     foreground='#7a4a10', font=('Segoe UI', 20, 'bold'),
                                     anchor='center')
        self.memory_value.pack(fill=tk.X)

        self.stats_label = ttk.Label(parent, text='', foreground='gray', anchor=tk.W)
        self.stats_label.pack(fill=tk.X, pady=(0, 6))

        self.chart = HistoryChart(parent)
        self.chart.pack(fill=tk.BOTH, expand=True)

    # --- sampling ----------------------------------------------------------
    def _interval_seconds(self):
        try:
            return max(0.1, float(self.interval_var.get()))
        except (TypeError, ValueError):
            return 3.0

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
        self._timer = self.after(int(self._interval_seconds() * 1000), self._take_sample)

    def _on_sample_failed(self, message):
        self._sampling = False
        self.sample_label.config(text=message, foreground='#C62828')
        self._schedule_next()

    def _on_sample(self, sample):
        self._sampling = False
        self._samples_taken += 1
        self.sample_label.config(text='')

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
        self.sample_label.config(text='')
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
