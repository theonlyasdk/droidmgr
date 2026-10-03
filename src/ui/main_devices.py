"""MainWindow mixin: Devices tab, polling, selection, context menu."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional
from .dpi import scale_size, setup_window_dpi
from .device_details_dialog import DeviceDetailsDialog


class _DevicesTabMixin:
    """_DevicesTabMixin for MainWindow (see main_window.py)."""

    def _create_devices_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Connected Devices")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        columns = ('ID', 'Model', 'Status', 'Mirroring')
        self.device_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.device_tree.heading('#0', text='#')
        for col in columns:
            self.device_tree.heading(col, text=col)
            self.device_tree.column(col, width=scale_size(200, self.root))
        self.device_tree.column('#0', width=scale_size(50, self.root))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_tree.bind('<<TreeviewSelect>>', self._on_device_select)
        self.device_tree.bind('<Double-1>', self._on_device_double_click)
        self.device_tree.bind('<Button-3>', self._show_device_context_menu)
        self.device_tree.bind('<Button-2>', self._show_device_context_menu)
        
        self.no_devices_frame = ttk.Frame(list_frame)
        
        title_label = tk.Label(self.no_devices_frame, text="No Devices Connected", 
                              font=('Arial', 16, 'bold'))
        title_label.pack(pady=(60, 20))
        
        instructions = [
            "To connect an Android device:",
            "1. Enable Developer Options on your device",
            "   (Settings > About Phone > Tap 'Build Number' 7 times)",
            "2. Enable USB Debugging",
            "   (Settings > Developer Options > USB Debugging)",
            "3. Connect your device via USB cable",
            "4. Accept 'Allow USB Debugging' prompt on your device",
            "",
            "Your device will appear here once connected."
        ]
        
        for instruction in instructions:
            label = tk.Label(self.no_devices_frame, text=instruction, 
                           font=('Arial', 10), anchor=tk.W, justify=tk.LEFT)
            pady = 8 if instruction == "" else 2
            label.pack(anchor=tk.W, padx=100, pady=pady)
        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_devices_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_devices)
        self.refresh_devices_btn.pack(side=tk.LEFT, padx=2)
        
        self.mirror_btn = ttk.Button(btn_frame, text="Start Mirroring", command=self._toggle_mirroring)
        self.mirror_btn.pack(side=tk.LEFT, padx=2)
        
        self.scrcpy_settings_btn = ttk.Button(btn_frame, text="scrcpy Settings", command=self._show_scrcpy_settings)
        self.scrcpy_settings_btn.pack(side=tk.LEFT, padx=2)

        self.connect_wireless_btn = ttk.Button(btn_frame, text="Connect Wirelessly...", command=self._show_connect_wireless_dialog)
        self.connect_wireless_btn.pack(side=tk.LEFT, padx=2)
        
        return tab

    def _schedule_device_poll(self):
        """Schedule the next periodic device refresh, canceling any existing timer."""
        if self._device_poll_job is not None:
            try:
                self.root.after_cancel(self._device_poll_job)
            except Exception:
                pass
            self._device_poll_job = None

        if getattr(self, '_closing', False):
            return

        interval_sec = self.config.get('general', 'query_interval', 5)
        try:
            interval_ms = max(1000, int(float(interval_sec) * 1000))
        except (ValueError, TypeError):
            interval_ms = 5000

        self._device_poll_job = self.root.after(interval_ms, self._refresh_devices)

    def _refresh_devices(self):
        """Asynchronously query connected devices and update the device list."""
        if getattr(self, '_closing', False):
            return

        # Cancel any scheduled poll since we are running a refresh now
        if self._device_poll_job is not None:
            try:
                self.root.after_cancel(self._device_poll_job)
            except Exception:
                pass
            self._device_poll_job = None

        # If a background refresh is already running, mark pending and return
        if getattr(self, '_device_refresh_in_progress', False):
            self._device_refresh_pending = True
            return

        self._device_refresh_in_progress = True

        def bg_query():
            try:
                devices = self.device_manager.get_devices()
                fastboot_devices = self._add_fastboot_devices(devices)
                err = None
            except Exception as e:
                devices = []
                fastboot_devices = set()
                err = str(e)

            def apply():
                self._apply_device_refresh(devices, fastboot_devices, err)

            try:
                if not getattr(self, '_closing', False):
                    self.root.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=bg_query, daemon=True).start()

    def _apply_device_refresh(self, devices: List[Dict], fastboot_devices: set, error: Optional[str] = None):
        self._device_refresh_in_progress = False
        if getattr(self, '_closing', False):
            return

        try:
            if error is not None:
                self.has_devices = False
                self.selected_device = None
                self.logcat_view.set_device(None)
                self._update_tab_visibility()
                self._set_status(f"Device refresh error: {error}")
                return

            self._fastboot_devices = fastboot_devices
            self.has_devices = len(devices) > 0
            self._update_tab_visibility()

            if not hasattr(self, '_notified_device_statuses'):
                self._notified_device_statuses = {}

            problem_msgs = []
            current_statuses = {}

            registry = getattr(getattr(self, 'device_manager', None), 'registry', None)
            for device in devices:
                dev_id = device['id']
                st = device.get('status', '').lower()
                current_statuses[dev_id] = st
                # Heartbeat for the device database: no adb, identity only.
                if registry is not None:
                    try:
                        registry.record_seen(dev_id, device.get('model'), st)
                    except Exception:
                        pass
                display_status = device.get('status', 'Unknown')
                if st == 'unauthorized':
                    display_status = "Unauthorized (Check Phone Prompt)"
                    msg = f"Device '{dev_id}' is unauthorized. Please accept the USB debugging prompt on the device screen."
                    if self._notified_device_statuses.get(dev_id) != 'unauthorized':
                        problem_msgs.append(msg)
                elif st == 'offline':
                    display_status = "Offline (Reconnect Cable)"
                    msg = f"Device '{dev_id}' is offline. Try reconnecting the USB cable or restarting ADB."
                    if self._notified_device_statuses.get(dev_id) != 'offline':
                        problem_msgs.append(msg)
                elif st == 'fastboot':
                    # Not a fault: the device is in fastboot mode deliberately, so
                    # it is described rather than reported as a problem to fix.
                    display_status = "Fastboot Mode (no ADB)"

                device['display_status'] = display_status

            self._notified_device_statuses = current_statuses

            if problem_msgs:
                self._set_status("; ".join(problem_msgs))

            # Smart tree update: check if the device table actually changed
            # to avoid destroying selection and causing visible row flicker.
            existing_children = self.device_tree.get_children()
            new_rows = []
            for device in devices:
                mirroring = "Yes" if device.get('is_mirroring', False) else "No"
                new_rows.append((
                    str(device['id']),
                    str(device.get('model', 'Unknown')),
                    str(device.get('display_status', device['status'])),
                    str(mirroring)
                ))

            if len(existing_children) == len(new_rows):
                for child, row in zip(existing_children, new_rows):
                    if tuple(str(x) for x in self.device_tree.item(child, 'values')) != tuple(row):
                        self.device_tree.item(child, values=row)
            else:
                for item in existing_children:
                    self.device_tree.delete(item)
                for idx, row in enumerate(new_rows, 1):
                    self.device_tree.insert('', tk.END, text=str(idx), values=row)

            self._set_status(f"Found {len(devices)} device(s)")

            children = self.device_tree.get_children()
            device_ids = [d['id'] for d in devices]

            if self.selected_device and self.selected_device not in device_ids:
                disconnected_id = self.selected_device
                self.statusbar.config(text=f"WARNING: Device '{disconnected_id}' disconnected.", foreground='red')
                self.root.after(4000, lambda: self.statusbar.config(foreground='black'))

                if self.device_manager.scrcpy.is_mirroring(disconnected_id):
                    try:
                        self.device_manager.stop_mirroring(disconnected_id)
                    except Exception:
                        pass

            if children:
                if not self.selected_device or self.selected_device not in device_ids:
                    first_item = children[0]
                    self.device_tree.selection_set(first_item)
                    self.device_tree.focus(first_item)
                    self._on_device_select(None)
                else:
                    curr_idx = device_ids.index(self.selected_device)
                    selected_items = self.device_tree.selection()
                    target_item = children[curr_idx]
                    if not selected_items or selected_items[0] != target_item:
                        self.device_tree.selection_set(target_item)
            else:
                if self.selected_device is not None:
                    self.selected_device = None
                    self.logcat_view.set_device(None)
                    self._update_tab_visibility()

        except Exception as e:
            self.has_devices = False
            self.selected_device = None
            self.logcat_view.set_device(None)
            self._update_tab_visibility()
            self._set_status(f"Device refresh error: {e}")
        finally:
            if getattr(self, '_device_refresh_pending', False):
                self._device_refresh_pending = False
                self.root.after(50, self._refresh_devices)
            else:
                self._schedule_device_poll()

    def _on_device_select(self, event):
        selection = self.device_tree.selection()
        if selection:
            item = self.device_tree.item(selection[0])
            values = item['values']
            if values:
                self.selected_device = values[0]
                self._set_status(f"Selected device: {self.selected_device}")
                self._update_tab_visibility()
                self._update_button_states()
                self._enrich_device_profile(self.selected_device)
                
                # Update file manager device reference
                self.file_manager.selected_device = self.selected_device
                
                # An open history window follows the selection too. It is a
                # window of its own rather than a tab, so nothing else reaches
                # it, and without this it would keep graphing the device that
                # was selected before.
                window = getattr(self, 'process_history_window', None)
                if (window is not None and window.winfo_exists()
                        and window.device_id != self.selected_device):
                    window.set_device(self.selected_device)
                
                # Only refresh the currently active tab
                try:
                    current_tab_id = self.notebook.select()
                    current_tab_text = self.notebook.tab(current_tab_id, "text") if current_tab_id else ""
                except Exception:
                    current_tab_text = ""
                
                if current_tab_text != "Network" and hasattr(self, 'network_view'):
                    self.network_view.stop_polling()
                if current_tab_text != "Logcat" and hasattr(self, 'logcat_view'):
                    self.logcat_view.stop()

                if current_tab_text == "Processes":
                    self._refresh_processes()
                elif current_tab_text == "Applications":
                    self._refresh_apps()
                elif current_tab_text == "Files":
                    self.file_manager.refresh()
                    self.logcat_view.set_device(self.selected_device)
                elif current_tab_text == "Network":
                    self.network_view.set_device(self.selected_device)
                elif current_tab_text == "Logcat":
                    self.logcat_view.set_device(
                        self.selected_device, force_refresh=True, autostart=True)
                elif current_tab_text == "Shell":
                    self.shell_view.set_device(self.selected_device)
                else:
                    self.logcat_view.set_device(self.selected_device)
                    self.shell_view.set_device(self.selected_device)

    def _on_device_double_click(self, event):
        if self.selected_device:
            DeviceDetailsDialog(self.root, self.selected_device, self.device_manager)

    def _show_device_context_menu(self, event):
        """Show context menu for a device row in device_tree."""
        item = self.device_tree.identify_row(event.y)
        if item:
            self.device_tree.selection_set(item)
            self._on_device_select(None)
        
        if not self.selected_device:
            return

        menu = tk.Menu(self.root, tearoff=0)
        is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
        menu.add_command(
            label="Stop Mirroring" if is_mirroring else "Start Mirroring",
            command=self._toggle_mirroring
        )
        menu.add_separator()
        if ":" not in self.selected_device:
            menu.add_command(
                label="Connect Wirelessly...",
                command=self._show_connect_wireless_dialog
            )
        else:
            menu.add_command(
                label="Disconnect Wireless Device",
                command=self._disconnect_wireless_device
            )
        menu.add_command(
            label="Device Details",
            command=lambda: DeviceDetailsDialog(self.root, self.selected_device, self.device_manager)
        )
        menu.add_separator()
        menu.add_command(label="Refresh", command=self._refresh_devices)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _enrich_device_profile(self, device_id):
        """Fetch stable facts + root status once per session into the registry."""
        manager = getattr(self, 'device_manager', None)
        if not device_id or manager is None:
            return
        threading.Thread(
            target=lambda: manager.enrich_device_record(device_id),
            daemon=True).start()

