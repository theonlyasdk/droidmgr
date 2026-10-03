"""Dialog for configuring and connecting to Android devices wirelessly via ADB TCP/IP and Wireless Pairing.

Facade that re-exports the split wireless_* modules so existing imports
keep working (e.g. ``from .wireless_dialog import ConnectWirelesslyDialog``).
"""

import tkinter as tk

from .wireless_base import WirelessBaseMixin
from .wireless_usb_tab import WirelessUsbTabMixin
from .wireless_direct_tab import WirelessDirectTabMixin
from .wireless_pairing_tab import WirelessPairingMixin


class ConnectWirelesslyDialog(
    WirelessBaseMixin,
    WirelessUsbTabMixin,
    WirelessDirectTabMixin,
    WirelessPairingMixin,
    tk.Toplevel,
):
    """3-Tabbed Unified Wireless ADB Connection Dialog:
    - Tab 1: Via USB (TCP/IP 5555 setup & connect)
    - Tab 2: Direct IP Connect (manual IP:Port)
    - Tab 3: Pair with Code (Android 11+ wireless debugging)
    """


# Backward-compatible aliases
WirelessADBSetupDialog = ConnectWirelesslyDialog
ConnectWirelessDialog = ConnectWirelesslyDialog


__all__ = [
    'ConnectWirelesslyDialog',
    'WirelessADBSetupDialog',
    'ConnectWirelessDialog',
]
