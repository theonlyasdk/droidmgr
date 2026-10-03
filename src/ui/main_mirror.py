"""MainWindow mixin: mirroring, wireless, power, fastboot, root."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .wireless_dialog import ConnectWirelesslyDialog
from .scrcpy_overlay import ScrcpyOverlayToolbar
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .main_utils import _POWER_ACTIONS, _RECONNECT_POLL_DELAYS


class _MirrorMixin:
    """_MirrorMixin for MainWindow (see main_window.py)."""

    def _update_mirror_label(self, is_mirroring: bool):
        """Keep the mirroring toolbar button and menu item showing the same action."""
        label = "Stop Mirroring" if is_mirroring else "Start Mirroring"
        self.mirror_btn.config(text=label)
        self.device_menu.entryconfig(self.mirror_menu_index, label=label)

    def _toggle_mirroring(self):
        if not self._require_device():
            return
        
        is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
        
        if is_mirroring:
            try:
                self.device_manager.stop_mirroring(self.selected_device)
                self._update_mirror_label(False)
                self._set_status("Mirroring stopped")
            except Exception as e:
                self._show_error("Mirroring Error", str(e))
        else:
            def task():
                try:
                    settings = dict(self.mirror_settings)
                    window_title = f"Droidmgr - {self.selected_device}"
                    settings['window_title'] = window_title

                    process = self.device_manager.start_mirroring(self.selected_device, **settings)
                    
                    def start_overlay():
                        self._update_mirror_label(True)
                        self._set_status("Mirroring started")

                        def stop_cb(dev_id):
                            try:
                                self.device_manager.stop_mirroring(dev_id)
                            except Exception:
                                pass
                            self._update_mirror_label(False)
                            self._set_status("Mirroring stopped")

                        ScrcpyOverlayToolbar(
                            parent=self.root,
                            process=process,
                            device_id=self.selected_device,
                            device_manager=self.device_manager,
                            stop_callback=stop_cb,
                            show_settings_callback=self._show_scrcpy_settings,
                            take_screenshot_callback=self._take_screenshot,
                            record_screen_callback=self._record_screen,
                            window_title=window_title,
                        )
                        
                    self.root.after(0, start_overlay)
                except Exception as e:
                    msg = str(e)
                    self.root.after(0, lambda: self._show_error("Mirroring Error", msg))
            
            self._set_status("Starting screen mirroring...")
            threading.Thread(target=task, daemon=True).start()

    def _enable_tcpip_mode(self):
        """Open the wireless connection dialog with the USB Setup tab active."""
        self._show_connect_wireless_dialog(initial_tab=0)

    def _show_connect_wireless_dialog(self, initial_tab=None):
        """Show unified 3-tabbed dialog to connect to an Android device wirelessly."""
        ConnectWirelesslyDialog(
            parent=self.root,
            device_manager=self.device_manager,
            selected_device=self.selected_device,
            on_connected_callback=self._refresh_devices,
            initial_tab=initial_tab
        )

    def _disconnect_wireless_device(self):
        """Disconnect a connected wireless ADB device."""
        if not self.selected_device:
            messagebox.showinfo("Select Device", "Please select a connected wireless device to disconnect.", parent=self.root)
            return

        if ":" not in self.selected_device:
            messagebox.showinfo(
                "Not a Wireless Device",
                f"Device '{self.selected_device}' is connected via USB. You can simply unplug the USB cable.",
                parent=self.root
            )
            return

        dev_id = self.selected_device
        try:
            self.device_manager.disconnect_device(dev_id)
            self._set_status(f"Disconnected {dev_id}")
            self._refresh_devices()
        except Exception as e:
            self._show_error("Disconnect Error", str(e))

    def _power_action(self, action):
        """Reboot or power off the selected device, after confirming."""
        if not self._require_device():
            return

        label, target, detail = _POWER_ACTIONS[action]
        if not messagebox.askyesno(
                label,
                f"{label} device '{self.selected_device}'?\n\n{detail}\n\n"
                "Unsaved work on the device will be lost.",
                parent=self.root):
            return

        device_id = self.selected_device
        is_shutdown = action == 'shutdown'
        self._set_status(f"{label} requested...")

        def task():
            try:
                if is_shutdown:
                    self.device_manager.shutdown_device(device_id)
                else:
                    self.device_manager.reboot_device(device_id, target)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error(f"{label} Failed", msg))
                return
            self.root.after(0, lambda: self._on_power_sent(label, device_id, is_shutdown))

        threading.Thread(target=task, daemon=True).start()

    def _on_power_sent(self, label, device_id, is_shutdown):
        """Report a delivered power command and watch for the device coming back."""
        self._refresh_devices()
        self._set_status(f"{label} sent to {device_id}")
        # A powered-off device never comes back on its own.
        if not is_shutdown:
            for delay in _RECONNECT_POLL_DELAYS:
                self.root.after(delay, self._refresh_devices)

    def _add_fastboot_devices(self, devices):
        """Append the fastboot-mode devices adb cannot report, and return their serials.

        adb's device list drops a device the moment it enters fastboot mode,
        which would read here as a disconnect and take the row away with it. The
        fastboot binary still knows the device, so the row is put back from its
        answer; that is also what gives the return command something to act on.

        Returns:
            Set of serials that are sitting in fastboot mode
        """
        try:
            serials = set(self.device_manager.get_fastboot_devices())
        except Exception:
            serials = set()

        known = {device['id'] for device in devices}
        for serial in sorted(serials - known):
            # Model and mirroring are unknowable without adb, so both say so.
            devices.append({'id': serial, 'model': 'Unknown (fastboot)',
                            'status': 'fastboot', 'is_mirroring': False})
        return serials

    def _update_fastboot_menu_state(self):
        """Offer the way back only to a device fastboot can actually reach."""
        in_fastboot = (self.selected_device is not None
                       and self.selected_device in self._fastboot_devices)
        self.device_menu.entryconfig(self.fastboot_reboot_menu_index,
                                     state=tk.NORMAL if in_fastboot else tk.DISABLED)

    def _fastboot_reboot(self):
        """Boot a fastboot-mode device back into Android, after confirming."""
        if not self._require_device(require_ready=False):
            return

        device_id = self.selected_device
        if not messagebox.askyesno(
                'Reboot from Fastboot',
                f"Reboot device '{device_id}' out of fastboot mode and back into "
                "Android?\n\nIt will restart normally. Nothing is written to the "
                "device.",
                parent=self.root):
            return

        self._set_status(f"Rebooting {device_id} from fastboot...")

        def task():
            try:
                self.device_manager.fastboot_reboot(device_id)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error('Fastboot Reboot Failed', msg))
                return
            self.root.after(0, lambda: self._on_fastboot_reboot_sent(device_id))

        threading.Thread(target=task, daemon=True).start()

    def _on_fastboot_reboot_sent(self, device_id):
        self._refresh_devices()
        self._set_status(f"{device_id} is rebooting from fastboot")
        for delay in _RECONNECT_POLL_DELAYS:
            self.root.after(delay, self._refresh_devices)

    def _check_root_access(self):
        """Report whether the selected device gives adb root access."""
        if not self._require_device():
            return

        device_id = self.selected_device
        self._set_status("Checking root access...")

        def task():
            try:
                status = self.device_manager.get_root_status(device_id)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Root Check Failed", msg))
                return
            try:
                registry = getattr(self.device_manager, 'registry', None)
                if registry is not None:
                    registry.record_root(device_id, status)
            except Exception:
                pass
            self.root.after(0, lambda: self._show_root_status(status))

        threading.Thread(target=task, daemon=True).start()

    def _show_root_status(self, status):
        """Explain what the root check found."""
        uid = status.get('shell_uid') or 'unknown'
        su_path = status.get('su_path')

        if status.get('adb_root'):
            summary = ("adb is running as root (uid 0).\n"
                       "System files and commands are unrestricted.")
        elif su_path:
            summary = (f"adb is not root (shell uid {uid}).\n\n"
                       f"An su binary is present at:\n{su_path}\n\n"
                       "It may still need approval on the device screen, or be limited "
                       "to certain apps.")
        else:
            summary = (f"adb is not root (shell uid {uid}).\n\n"
                       "No su binary found. The device is not rooted, or root is hidden.")

        self._set_status("Root check complete: "
                         + ("root available" if status.get('adb_root') else "not root"))
        messagebox.showinfo("Root Access", summary, parent=self.root)

    def _reconnect_adb(self):
        """Ask the adb server to re-establish device connections."""
        self._set_status("Reconnecting through ADB...")

        def task():
            try:
                output = self.device_manager.reconnect_devices()
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Reconnect Failed", msg))
                return
            self.root.after(0, lambda: self._on_adb_reconnected(output))

        threading.Thread(target=task, daemon=True).start()

    def _on_adb_reconnected(self, output):
        self._refresh_devices()
        detail = ' '.join((output or '').split())
        self._set_status(f"ADB reconnect sent{': ' + detail if detail else ''}")
        for delay in _RECONNECT_POLL_DELAYS:
            self.root.after(delay, self._refresh_devices)

