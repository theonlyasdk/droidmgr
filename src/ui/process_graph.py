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

from .process_chart import (
    DEVICE_KEY, MAX_SAMPLES, INTERVALS, HISTORY_CHOICES, TOP_CHOICES,
    CHART_BACKGROUND, CHART_GRID, CHART_AXIS_TEXT,
    CPU_LINE, CPU_FILL, MEMORY_LINE,
    VALUE_CPU_BACKGROUND, VALUE_MEMORY_BACKGROUND,
    HistoryChart,
)
from .process_list import ProcessListMixin
from .process_history import ProcessHistoryWindow


__all__ = ['ProcessHistoryWindow', 'HistoryChart', 'ProcessListMixin',
           'DEVICE_KEY', 'MAX_SAMPLES', 'INTERVALS', 'HISTORY_CHOICES', 'TOP_CHOICES',
           'CHART_BACKGROUND', 'CHART_GRID', 'CHART_AXIS_TEXT',
           'CPU_LINE', 'CPU_FILL', 'MEMORY_LINE',
           'VALUE_CPU_BACKGROUND', 'VALUE_MEMORY_BACKGROUND']
