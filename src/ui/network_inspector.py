"""Network inspector tab for the main window and device details dialog.

Facade that re-exports the split network_* modules so existing imports
keep working (e.g. ``from .network_inspector import NetworkInspector``).
"""

from tkinter import ttk

from .network_format import (
    TABLE_HEIGHT,
    MISSING,
    _CONNECTED_STATES,
    _NO_SIGNAL_DBM,
    _format_bytes,
    _format_ms,
    _is_private_ip,
    sanitize_network_data,
)
from .network_tables import _SortableTree
from .network_panels import NetworkPanelsMixin
from .network_polling import NetworkPollingMixin
from .network_refresh import NetworkRefreshMixin
from .network_diag import NetworkDiagMixin


class NetworkInspector(
    NetworkPanelsMixin,
    NetworkPollingMixin,
    NetworkRefreshMixin,
    NetworkDiagMixin,
    ttk.Frame,
):
    """The network inspector: Wi-Fi, cellular, routes, data usage, history, sockets."""


__all__ = [
    'NetworkInspector',
    'TABLE_HEIGHT',
    'MISSING',
    'sanitize_network_data',
]
