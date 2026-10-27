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
        
        self.screenshot_btn = ttk.Button(btn_frame, text="Take Screenshot", command=self._take_screenshot)
        self.screenshot_btn.pack(side=tk.LEFT, padx=2)
        
        self.scrcpy_settings_btn = ttk.Button(btn_frame, text="scrcpy Settings", command=self._show_scrcpy_settings)
        self.scrcpy_settings_btn.pack(side=tk.LEFT, padx=2)

        self.connect_wireless_btn = ttk.Button(btn_frame, text="Connect Wirelessly...", command=self._show_connect_wireless_dialog)
        self.connect_wireless_btn.pack(side=tk.LEFT, padx=2)

        # Tool version banner and 'Getting started' card sit above the device
        # list; both are packed from the refresh path only when they change.
        warning_style = ttk.Style(self.root)
        warning_style.configure('Warning.TFrame', background='#FFF3CD')
        warning_style.configure('Warning.TLabel', background='#FFF3CD',
                                foreground='#856404')

        self._device_list_frame = list_frame
        self._version_banner_frame = None
        self._tool_versions = None
        self._tool_version_check_started = False
        self._tool_banner_dismissed = False
        self._checklist_signature = ()
        self._checklist_visible = False
        self._last_seen_devices = None

        self.checklist_frame = ttk.LabelFrame(tab, text="Getting started")

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
            # The once-per-session adb/fastboot version check runs in its own
            # worker off this refresh, so it never blocks the device query.
            self._start_tool_version_check()
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

        # What the last refresh knew, for the checklist card and the
        # once-per-session tool version check above it.
        self._last_seen_devices = list(devices or [])

        try:
            if error is not None:
                self.has_devices = False
                self.selected_device = None
                self.logcat_view.set_device(None)
                self._update_tab_visibility()
                self._set_status(f"Device refresh error: {error}")
                self._update_setup_checklist()
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
            self._update_setup_checklist()

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

    # ---- Tool version guard banner --------------------------------------

    def _start_tool_version_check(self):
        """Run the one-off adb/fastboot version check in a worker thread.

        Started once per session from the first device refresh; the result is
        stored on the window and used by the banner and the checklist card.
        """
        if self._tool_version_check_started:
            return
        self._tool_version_check_started = True

        def task():
            versions = None
            try:
                versions = self.device_manager.get_tool_versions()
            except Exception:
                versions = None
            try:
                if not getattr(self, '_closing', False):
                    self.root.after(0, lambda: self._apply_tool_versions(versions))
            except Exception:
                pass

        threading.Thread(target=task, daemon=True).start()

    def _apply_tool_versions(self, versions):
        """Store the version check's answer and decide whether the banner shows.

        Only evaluated once: if the banner does not apply, later refreshes say
        nothing (silence is success); if the user dismisses it with ✕, it stays
        hidden for the rest of the session.
        """
        self._tool_versions = versions if isinstance(versions, dict) else {}
        self._update_setup_checklist()

        if getattr(self, '_tool_banner_dismissed', False):
            return

        versions = self._tool_versions
        adb_version = versions.get('adb') or None
        fastboot_version = versions.get('fastboot') or None
        adb_ok = bool(versions.get('adb_ok'))
        fastboot_ok = bool(versions.get('fastboot_ok'))

        text = None
        if adb_ok and fastboot_ok:
            adb_major_minor = self._tool_major_minor(adb_version)
            fastboot_major_minor = self._tool_major_minor(fastboot_version)
            if (adb_major_minor and fastboot_major_minor
                    and adb_major_minor != fastboot_major_minor):
                text = (f"adb and fastboot builds differ (adb {adb_version}, "
                        f"fastboot {fastboot_version}): reinstall platform-tools "
                        "so both tools come from the same bundle.")
        elif adb_ok and not fastboot_ok:
            text = (f"fastboot executable not found / not runnable — flashing and "
                    f"fastboot device listing will not work (adb {adb_version}, "
                    "fastboot not readable).")

        if text:
            self._show_version_banner(text)

    @staticmethod
    def _tool_major_minor(version):
        """(major, minor) of an 'x.y.z' tool version, None when oddly shaped."""
        try:
            parts = str(version).split('.')
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError, AttributeError):
            return None

    def _show_version_banner(self, text):
        """Create or update the warning banner and pack it above the list."""
        if self._version_banner_frame is None:
            frame = ttk.Frame(self._device_list_frame.master,
                              style='Warning.TFrame')
            label = ttk.Label(
                frame,
                style='Warning.TLabel',
                text=text,
                anchor='w', justify=tk.LEFT,
                wraplength=scale_size(720, self.root))
            close_btn = ttk.Button(
                frame, text='✕', width=3,
                command=self._dismiss_version_banner)
            close_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=2)
            label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                       padx=(8, 4), pady=2)
            self._version_banner_frame = frame
            self._version_banner_label = label
        else:
            self._version_banner_label.config(text=text)

        anchor = self.checklist_frame if self._checklist_visible \
            else self._device_list_frame
        self._version_banner_frame.pack(fill=tk.X, pady=0, before=anchor)

    def _dismiss_version_banner(self):
        """Hide the version banner; it stays hidden for the rest of the session."""
        self._tool_banner_dismissed = True
        if self._version_banner_frame is not None:
            self._version_banner_frame.pack_forget()

    # ---- 'Getting started' checklist card --------------------------------

    def _update_setup_checklist(self):
        """Rebuild the 'Getting started' card from the last refresh's data.

        Every row comes from state the refresh already collected (the device
        list with its statuses, and the one-off tool version check); nothing
        here queries a device. The card is packed only while it has rows, so
        "all fine" carries no empty space, and identical row sets rebuild
        nothing.
        """
        if getattr(self, '_closing', False):
            return

        rows = []  # (text, button text or None, action or None)

        versions = getattr(self, '_tool_versions', None) or {}
        if versions and not versions.get('adb_ok'):
            rows.append(("adb was not found so the app cannot reach any device.",
                         "Locate adb...", self._show_preferences))

        devices = getattr(self, '_last_seen_devices', None)
        if devices is not None and not devices:
            rows.append(("No devices visible yet: plug the phone over USB, enable "
                         "USB debugging, and tap Trust/Allow on its screen.",
                         "Refresh", self._refresh_devices))

        by_status = {}
        for device in devices or []:
            status = (device.get('status') or '').lower()
            if status and status != 'device':
                by_status.setdefault(status, []).append(device)
        for status in sorted(by_status):
            count = len(by_status[status])
            subject = f"{count} devices sit" if count > 1 else "a device sits"
            rows.append((f"{subject} in '{status}' state — "
                         f"{self._status_hint(status)}", None, None))

        signature = tuple((row[0], row[1]) for row in rows)
        if signature == getattr(self, '_checklist_signature', None):
            return  # same rows as before; no rebuild, no reflow
        self._checklist_signature = signature
        self._rebuild_checklist(rows)

    @staticmethod
    def _status_hint(status: str) -> str:
        """The advice shown for a device sitting in a given state."""
        if status == 'unauthorized':
            return "approve the RSA / USB debugging prompt on its screen"
        if status == 'offline':
            return "replug the cable or use Device menu > Reconnect ADB"
        if status == 'fastboot':
            return "it is in fastboot mode by choice; Device menu > " \
                   "Reboot from fastboot brings it back"
        return "replug the cable; details are in the status bar"

    def _rebuild_checklist(self, rows):
        """Replace the card's rows and pack the card only when it has any."""
        card = self.checklist_frame
        for child in card.winfo_children():
            child.destroy()
        for text, button_text, action in rows:
            row = ttk.Frame(card)
            row.pack(fill=tk.X, padx=8, pady=3)
            label = ttk.Label(row, text=text, anchor='w', justify=tk.LEFT,
                              wraplength=scale_size(700, self.root))
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if button_text:
                ttk.Button(row, text=button_text, command=action,
                           width=12).pack(side=tk.RIGHT, padx=(8, 0), pady=1)
        if rows:
            card.pack(fill=tk.X, padx=5, pady=0,
                      before=self._device_list_frame)
        else:
            card.pack_forget()
        self._checklist_visible = bool(rows)

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
        menu.add_command(
            label="Take Screenshot",
            command=self._take_screenshot
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

