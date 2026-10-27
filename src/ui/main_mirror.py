"""MainWindow mixin: mirroring, wireless, power, fastboot, root."""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .wireless_dialog import ConnectWirelesslyDialog
from .scrcpy_overlay import ScrcpyOverlayToolbar
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .error_detail_dialog import ErrorDetailDialog
from .flash_progress_dialog import FlashProgressDialog
from .sideload_progress_dialog import SideloadProgressDialog
from .post_flash_dialog import PostFlashChoiceDialog
from .wireless_mirror_dialog import WirelessMirrorDialog
from .apk_install_progress import format_elapsed
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
        # Flashing is possible from both states: an adb device is rebooted to
        # the bootloader first, so it needs no fastboot-mode membership.
        self.device_menu.entryconfig(self.fastboot_flash_menu_index,
                                     state=tk.NORMAL if self.selected_device
                                     else tk.DISABLED)

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

    def _flash_recovery_image(self):
        """Pick a recovery image on the PC and flash it to the device."""
        self._flash_boot_partition_image('recovery')

    def _flash_boot_partition_image(self, partition: str):
        """Flash a chosen image to a boot partition, and expose every problem.

        The gates run in order, each one its own dialog: file choice,
        validation (all problems reported at once, with Copy), a fastboot-mode
        check (offering the reboot into the bootloader when it is not there
        already), a final confirm of the write itself, then the progress
        window while the device is reached and flashed. Success asks whether
        to reboot; failure shows fastboot's output in a copyable detail box.
        """
        if not self._require_device(require_ready=False):
            return

        device_id = self.selected_device

        path = filedialog.askopenfilename(
            title=f"Choose a {partition} image",
            filetypes=[(f"{partition} image (*.img)", "*.img"),
                       ("All files", "*.*")],
            parent=self.root)
        if not path:
            return

        problems = self.device_manager.validate_flash_image(path, partition)
        if problems:
            ErrorDetailDialog(
                self.root, 'Image Validation Failed',
                f"The chosen image cannot be flashed to '{partition}':",
                "\n".join(problems))
            return

        image_name = os.path.basename(path)
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            size_mb = 0.0

        in_fastboot = device_id in getattr(self, '_fastboot_devices', set())
        if not in_fastboot and not messagebox.askyesno(
                'Not in Fastboot Mode',
                f"Device '{device_id}' is not in fastboot mode, so nothing can be "
                "flashed to it yet.\n\nReboot it to the bootloader (fastboot) now, "
                "and start the flash once it is there?",
                parent=self.root):
            self._set_status('Flash cancelled - the device must be in fastboot mode')
            return

        if in_fastboot:
            # The bootloader gets its say before the write is confirmed: a
            # locked one rejects the flash server-side anyway.
            self._set_status('Checking bootloader state...')
            self.root.config(cursor='watch')
            try:
                preflight_ok = self._flash_preflight(device_id)
            finally:
                self.root.config(cursor='')
            if not preflight_ok:
                self._set_status('Flash cancelled')
                return

        if not messagebox.askyesno(
                f'Flash {partition.title()} Image',
                f"Flash '{image_name}' ({size_mb:.1f} MB) to the {partition} "
                f"partition of device '{device_id}'?\n\n"
                f"This rewrites the partition permanently.\n\nA wrong or corrupt "
                f"image can leave the device unable to boot."
                + ('' if in_fastboot else
                   "\n\nThe device reboots to the bootloader first; the flash "
                   "starts when fastboot sees it."),
                parent=self.root):
            self._set_status('Flash cancelled')
            return

        dialog = FlashProgressDialog(self.root, image_name, size_mb, partition,
                                     device_id, waiting_for_fastboot=not in_fastboot)

        def report_error(message):
            self.root.after(0, lambda: self._on_flash_error(dialog, device_id, message))

        def task():
            if not in_fastboot:
                self.root.after(0, lambda: dialog.set_stage(
                    f"Rebooting '{device_id}' to the bootloader..."))
                try:
                    self.device_manager.reboot_device(device_id, 'bootloader')
                except Exception as e:
                    report_error(
                        f"Could not reboot '{device_id}' to the bootloader, so the "
                        f"flash was not attempted:\n\n{e}")
                    return
                self._set_status_async(f"Waiting for {device_id} to reach fastboot mode...")

                deadline = time.monotonic() + 150
                reached = False
                while time.monotonic() < deadline:
                    try:
                        serials = self.device_manager.get_fastboot_devices()
                    except Exception:
                        serials = []
                    if device_id in serials:
                        reached = True
                        break
                    time.sleep(3)
                if not reached:
                    report_error(
                        f"'{device_id}' did not reach fastboot mode within 150 s after "
                        "rebooting to the bootloader, so the flash was not attempted.\n\n"
                        "Possible causes: a cable or hub the bootloader does not talk "
                        "through, drivers missing for fastboot mode, or the device "
                        "leaving the bootloader on its own.")
                    return
                self.root.after(0, lambda: dialog.set_stage(
                    f"Fastboot sees '{device_id}'; flashing now..."))

            # Preflight the bootloader once fastboot can be asked (running
            # before the reboot would mean two reboots for one flash). A
            # warning dialog must come from the UI thread, so the decision is
            # handed back over an event. Devices that were already in fastboot
            # were preflighted during gating.
            if not in_fastboot:
                self._set_status_async('Checking bootloader state...')
                decision = {'go': False}
                done = threading.Event()

                def ask_preflight():
                    decision['go'] = self._flash_preflight(device_id)
                    done.set()

                self.root.after(0, ask_preflight)
                done.wait()
                if not decision['go']:
                    self.root.after(0, dialog.close)
                    self.root.after(0, self._refresh_devices)
                    self._set_status_async('Flash cancelled - locked bootloader')
                    return

            self.root.after(0, lambda: dialog.set_stage(
                f"Writing '{image_name}' to {partition}; this can take a while..."))
            try:
                started = time.monotonic()
                self.device_manager.flash_fastboot_image(device_id, path, partition)
                elapsed = time.monotonic() - started
            except Exception as e:
                report_error(str(e))
                return

            self.root.after(0, lambda: self._on_flash_success(
                dialog, device_id, image_name, partition, elapsed, path))

        threading.Thread(target=task, daemon=True).start()

    def _set_status_async(self, message):
        """Set the status bar from any thread."""
        self.root.after(0, lambda: self._set_status(message))

    def _flash_preflight(self, device_id: str) -> bool:
        """Warn about a locked bootloader before spending the write on it.

        A truly locked device rejects flashing server-side, so the user is
        asked explicitly (default: cancel). An unreadable unlocked-state
        continues silently - nagging on every flash a build cannot answer
        would be worse than the uncertainty.
        """
        try:
            unlocked = self.device_manager.fastboot_unlocked(device_id)
        except Exception:
            unlocked = None
        try:
            ability = self.device_manager.fastboot_get_unlock_ability(device_id)
        except Exception:
            ability = None

        if unlocked is not False:
            self._set_status('Bootloader preflight: '
                             + ('unlocked' if unlocked is True
                                else 'state unreadable, continuing'))
            return True

        lines = [f"The bootloader of '{device_id}' is LOCKED, so the flash is "
                 "expected to be rejected by the device."]
        if ability == '0':
            lines.append("More than that: 'OEM unlocking' has not been enabled "
                         "in the device's Developer options "
                         "(get_unlock_ability = 0), so the bootloader cannot "
                         "even be unlocked from fastboot yet.")
        elif ability is None:
            lines.append("The unlock-ability state could not be read; check "
                         "'OEM unlocking' under Developer options manually.")
        lines.append("Flash anyway (some devices tolerate writes while locked), "
                     "or cancel?")

        return messagebox.askyesno('Locked Bootloader Warning',
                                   '\n\n'.join(lines),
                                   parent=self.root)

    def _on_flash_success(self, dialog, device_id, image_name, partition,
                          elapsed, image_path):
        dialog.close()
        self._refresh_devices()
        self._set_status(f"Flashed {image_name} in {format_elapsed(elapsed)}")

        choice = PostFlashChoiceDialog(
            self.root, image_name, partition, elapsed).chosen

        if choice == 'reboot':
            self._set_status(f"Rebooting {device_id} from fastboot...")

            def task():
                try:
                    self.device_manager.fastboot_reboot(device_id)
                except Exception as e:
                    msg = str(e)
                    self.root.after(0, lambda: self._show_error(
                        'Fastboot Reboot Failed', msg))
                    return
                self.root.after(0, lambda: self._on_fastboot_reboot_sent(device_id))

            threading.Thread(target=task, daemon=True).start()
        elif choice == 'testboot':
            self._set_status(
                f"Test-booting '{image_name}' on '{device_id}' (nothing is written)...")

            def task():
                try:
                    started = time.monotonic()
                    self.device_manager.fastboot_boot(device_id, image_path)
                    elapsed = format_elapsed(time.monotonic() - started)
                except Exception as e:
                    msg = str(e)

                    def show_fail():
                        self._set_status('Test-boot failed')
                        ErrorDetailDialog(
                            self.root, 'Test-Boot Failed',
                            f"'{image_name}' was not booted on '{device_id}':",
                            msg)

                    self.root.after(0, show_fail)
                    return

                self.root.after(0, lambda: self._on_test_boot_done(
                    device_id, image_name, elapsed))

            threading.Thread(target=task, daemon=True).start()
        else:
            self._set_status(f"Device '{device_id}' left in fastboot mode")

    def _on_test_boot_done(self, device_id: str, image_name: str, elapsed: str):
        self._set_status(f"Test-booted '{image_name}' in {elapsed}")
        messagebox.showinfo(
            'Test-Boot Started',
            f"'{image_name}' is starting on '{device_id}' "
            f"(took {elapsed}).\n\n"
            "Nothing was written to any partition: the image runs from "
            "memory, and the device returns to fastboot when it exits.",
            parent=self.root)

    def _on_flash_error(self, dialog, device_id, message):
        dialog.close()
        self._refresh_devices()
        self._set_status('Flash failed')
        ErrorDetailDialog(self.root, 'Flash Failed',
                          f"The flash to '{device_id}' did not complete:",
                          message)

    def _apply_update_from_file(self):
        """Apply a chosen OTA package to the device over `adb sideload`.

        Same gate order as the flasher: file choice, validation (every
        problem at once, with Copy), a sideload-mode check offering the
        reboot into that state (decline cancels), a confirm of the apply
        itself, then the progress window. The percent adb prints while
        streaming drives a determinate bar; failure shows adb's console in a
        copyable detail box.
        """
        if not self._require_device():
            return
        device_id = self.selected_device

        path = filedialog.askopenfilename(
            title='Choose an OTA update package',
            filetypes=[('Update package (*.zip)', '*.zip'),
                       ('All files', '*.*')],
            parent=self.root)
        if not path:
            return

        problems = self.device_manager.validate_sideload_package(path)
        if problems:
            ErrorDetailDialog(
                self.root, 'Update Package Validation Failed',
                'The chosen package cannot be applied yet:',
                "\n".join(problems))
            return

        package_name = os.path.basename(path)
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            size_mb = 0.0

        in_sideload = self._device_in_sideload(device_id)
        if not in_sideload and not messagebox.askyesno(
                'Not in Sideload Mode',
                f"Update packages are applied from recovery's 'Apply update "
                f"from ADB' screen, and '{device_id}' is not there now.\n\n"
                "Reboot it into sideload mode so the update can start? The "
                "device restarts into recovery and the transfer begins as "
                "soon as adb sees it there.",
                parent=self.root):
            self._set_status('Update cancelled - the device must be in sideload mode')
            return

        if not messagebox.askyesno(
                'Apply Update Package',
                f"Apply '{package_name}' ({size_mb:.1f} MB) to '{device_id}'?\n\n"
                "The package streams and installs in one session; the device "
                "applies whatever it receives. Do not unplug it.\n\n"
                "A wrong or corrupt package leaves the system in a partial "
                "or unbootable state."
                + ('' if in_sideload else
                   "\n\nThe device reboots into sideload mode first; the "
                   "transfer starts when adb sees it there."),
                parent=self.root):
            self._set_status('Update cancelled')
            return

        dialog = SideloadProgressDialog(self.root, package_name, size_mb,
                                        device_id,
                                        waiting_for_sideload=not in_sideload)

        def report_error(message):
            self.root.after(0, lambda: self._on_sideload_error(
                dialog, device_id, message))

        def task():
            if not in_sideload:
                self.root.after(0, lambda: dialog.set_stage(
                    f"Rebooting '{device_id}' into sideload mode..."))
                try:
                    self.device_manager.reboot_device(device_id, 'sideload')
                except Exception as e:
                    report_error(
                        f"Could not reboot '{device_id}' into sideload mode, "
                        f"so the update was not attempted:\n\n{e}")
                    return
                self._set_status_async(
                    f"Waiting for {device_id} to reach sideload mode...")

                deadline = time.monotonic() + 120
                reached = False
                while time.monotonic() < deadline:
                    if self._device_in_sideload(device_id):
                        reached = True
                        break
                    time.sleep(3)
                if not reached:
                    report_error(
                        f"'{device_id}' did not reach sideload mode within "
                        "120 s, so the update was not attempted.\n\n"
                        "Possible causes: the recovery does not offer an "
                        "'Apply update from ADB' entry, the reboot was "
                        "interrupted, or the USB connection dropped.")
                    return
                self.root.after(0, lambda: dialog.set_stage(
                    f"Device '{device_id}' is in sideload mode; streaming..."))

            self.root.after(0, lambda: dialog.set_stage(
                f"Streaming '{package_name}' to '{device_id}'..."))
            try:
                started = time.monotonic()
                self.device_manager.sideload_package(
                    device_id, path,
                    progress_cb=lambda percent: self.root.after(
                        0, lambda p=percent: dialog.set_percent(p)))
                elapsed = time.monotonic() - started
            except Exception as e:
                report_error(str(e))
                return

            self.root.after(0, lambda: self._on_sideload_success(
                dialog, device_id, package_name, elapsed))

        threading.Thread(target=task, daemon=True).start()

    def _device_in_sideload(self, device_id: str) -> bool:
        """Whether the selected device is currently in adb's sideload state."""
        try:
            for info in self.device_manager.get_devices():
                if info.get('id') == device_id and info.get('status') == 'sideload':
                    return True
        except Exception:
            pass
        return False

    def _on_sideload_success(self, dialog, device_id, package_name, elapsed):
        dialog.close()
        self._refresh_devices()
        self._set_status(f"Applied {package_name} in {format_elapsed(elapsed)}")
        if messagebox.askyesno(
                'Update Applied',
                f"'{package_name}' was applied to '{device_id}' in "
                f"{format_elapsed(elapsed)}.\n\n"
                "The device is still sitting in sideload/recovery. Reboot it "
                "back into Android now?",
                parent=self.root):
            self._set_status(f"Rebooting {device_id}...")

            def task():
                try:
                    self.device_manager.reboot_device(device_id)
                except Exception as e:
                    msg = str(e)
                    self.root.after(0, lambda: self._show_error(
                        'Reboot Failed', msg))
                    return
                self.root.after(0, lambda: self._on_sideload_reboot_sent(device_id))

            threading.Thread(target=task, daemon=True).start()

    def _on_sideload_reboot_sent(self, device_id):
        self._refresh_devices()
        self._set_status(f"{device_id} is rebooting")
        for delay in _RECONNECT_POLL_DELAYS:
            self.root.after(delay, self._refresh_devices)

    def _on_sideload_error(self, dialog, device_id, message):
        dialog.close()
        self._refresh_devices()
        self._set_status('Update failed')
        ErrorDetailDialog(self.root, 'Sideload Failed',
                          f"The update to '{device_id}' did not complete:",
                          message)

    def _wireless_mirror(self):
        """One entry point from 'a device on this desk' to a mirrored window.

        adb connects to the remembered (or freshly typed) address for the
        selected device, then the mirroring starts on that connection. The
        handshake lives in the dialog; this only orchestrates the two steps.
        """
        if not self._require_device():
            return
        device_id = self.selected_device

        target = getattr(self, '_wireless_mirror_target', None)
        try:
            if self.device_manager.scrcpy.is_mirroring(device_id) or (
                    target and self.device_manager.scrcpy.is_mirroring(target)):
                self._set_status('Already mirroring - stop it first')
                return
        except Exception:
            pass

        remembered = self.config.get('wireless_mirror', device_id, '')
        WirelessMirrorDialog(
            self.root, self.device_manager, device_id, remembered,
            on_connected=lambda address: self._start_wireless_mirror(
                device_id, address))

    def _start_wireless_mirror(self, device_id: str, address: str):
        self.config.set('wireless_mirror', device_id, address)
        self._set_status(f"Starting wireless mirror on '{address}'...")

        def task():
            try:
                settings = dict(self.mirror_settings)
                window_title = f"Droidmgr - {address}"
                settings['window_title'] = window_title

                process = self.device_manager.start_mirroring(address, **settings)
                self.root.after(0, lambda: self._on_wireless_mirror_started(
                    device_id, address, window_title, process))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error(
                    'Wireless Mirror Error', msg))

        threading.Thread(target=task, daemon=True).start()

    def _on_wireless_mirror_started(self, device_id, address, window_title,
                                    process):
        self._wireless_mirror_target = address
        self._update_mirror_label(True)
        self._set_status(f"Mirroring '{device_id}' over Wi-Fi ({address})")

        def stop_cb(dev_id):
            try:
                self.device_manager.stop_mirroring(dev_id)
            except Exception:
                pass
            self._wireless_mirror_target = None
            self._update_mirror_label(False)
            self._set_status('Mirroring stopped')

        ScrcpyOverlayToolbar(
            parent=self.root,
            process=process,
            device_id=address,
            device_manager=self.device_manager,
            stop_callback=stop_cb,
            show_settings_callback=self._show_scrcpy_settings,
            take_screenshot_callback=self._take_screenshot,
            record_screen_callback=self._record_screen,
            window_title=window_title,
        )

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

