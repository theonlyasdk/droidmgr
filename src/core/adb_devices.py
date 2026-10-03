"""ADBManager mixin: device enumeration, identity, power, fastboot, root."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from .adb_base import ADBCommandError, ADBDeviceNotFoundError, FastbootNotFoundError


class _DevicesMixin:
    """_DevicesMixin for ADBManager (see adb_manager.py)."""

    def get_devices(self) -> List[Dict[str, str]]:
        output = self._run_command(['devices', '-l'])
        devices = []
        
        for line in output.split('\n')[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 2:
                device_id = parts[0]
                status = parts[1]
                
                info = {'id': device_id, 'status': status}
                
                for part in parts[2:]:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        info[key] = value
                
                devices.append(info)
        
        return devices

    def get_device_model(self, device_id: str) -> str:
        try:
            return self._run_command(['shell', 'getprop', 'ro.product.model'], device_id)
        except RuntimeError:
            return "Unknown"

    def get_detailed_device_info(self, device_id: str, step_cb=None) -> Dict[str, str]:
        """Fetch detailed non-confidential device information including CPU and RAM."""
        info = {}
        try:
            if step_cb:
                step_cb("Querying device identity and system properties...")
            # Basic props
            info['model'] = self.get_device_model(device_id)
            info['manufacturer'] = self._run_command(['shell', 'getprop', 'ro.product.manufacturer'], device_id)
            info['android_version'] = self._run_command(['shell', 'getprop', 'ro.build.version.release'], device_id)
            info['android_codename'] = self._run_command(['shell', 'getprop', 'ro.build.version.codename'], device_id)
            info['build_id'] = self._run_command(['shell', 'getprop', 'ro.build.display.id'], device_id)
            info['kernel'] = self._run_command(['shell', 'uname', '-rs'], device_id)
            info['product_name'] = self._run_command(['shell', 'getprop', 'ro.product.name'], device_id)
            info['serial'] = device_id

            # CPU Info
            if step_cb:
                step_cb("Querying CPU architecture and SoC...")
            # Try ro.soc.model first (Android 12+)
            soc = self._run_command(['shell', 'getprop', 'ro.soc.model'], device_id).strip()
            if not soc:
                soc = self._run_command(['shell', 'getprop', 'ro.board.platform'], device_id).strip()
            
            # Extract from /proc/cpuinfo for more detail if needed
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            hardware = ""
            for line in cpuinfo.split('\n'):
                if line.startswith('Hardware'):
                    hardware = line.split(':', 1)[1].strip()
                    break
            
            info['cpu'] = soc if soc else (hardware if hardware else "Unknown")
            if hardware and soc and hardware.lower() != soc.lower():
                info['cpu'] = f"{soc} ({hardware})"

            # Memory Info
            if step_cb:
                step_cb("Querying RAM and memory metrics...")
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
            
            if total_kb:
                total_gb = total_kb / (1024 * 1024)
                avail_gb = avail_kb / (1024 * 1024)
                info['ram'] = f"{avail_gb:.1f} GB / {total_gb:.1f} GB free"
            else:
                info['ram'] = "Unknown"

        except Exception as e:
            info['error'] = str(e)
        return info

    def trigger_easter_egg(self, device_id: str) -> None:
        """Attempt to launch the Android Easter Egg activity."""
        # Common locations for Easter Egg
        activities = [
            "com.android.egg/.EasterEggActivity",
            "com.android.systemui/.DessertCase",
            "com.android.systemui/.BeanBag",
            "com.android.egg/com.android.egg.land.EasterEggActivity"
        ]
        
        for activity in activities:
            try:
                self._run_command(['shell', 'am', 'start', '-n', activity], device_id)
                return # Stop if one succeeds
            except:
                continue
        
        # Fallback to general intent
        try:
            self._run_command(['shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-n', 'com.android.egg/.EasterEggActivity'], device_id)
        except:
            pass

    def reboot_device(self, device_id: str, target: Optional[str] = None) -> str:
        """Reboot a device, optionally into recovery or the bootloader.

        Args:
            device_id: Device ID / serial number
            target: 'recovery', 'bootloader', 'sideload' or None for a normal reboot

        Returns:
            Output from the adb reboot command
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        args = ['reboot']
        if target:
            args.append(target)
        return self._run_command(args, device_id)

    def _fastboot_executable(self) -> Optional[str]:
        """The fastboot binary belonging to the adb this manager is using.

        fastboot ships inside the same platform-tools package as adb, so it is
        looked for beside the adb already configured before falling back to
        whatever is on PATH. None means fastboot is not installed, which is
        reported as a missing tool rather than a missing device.

        The answer is remembered, including when it is None, so a machine
        without fastboot costs one lookup rather than one per refresh.
        """
        if self._fastboot_path is not None:
            return self._fastboot_path or None

        executable = 'fastboot.exe' if os.name == 'nt' else 'fastboot'
        beside_adb = Path(self.adb_path).parent / executable
        if beside_adb.exists():
            self._fastboot_path = str(beside_adb)
            return self._fastboot_path

        on_path = shutil.which(executable)
        self._fastboot_path = on_path or ''
        return self._fastboot_path or None

    def _require_fastboot(self) -> str:
        executable = self._fastboot_executable()
        if not executable:
            raise FastbootNotFoundError(
                "fastboot was not found. It ships in Android platform-tools "
                "alongside adb; install platform-tools or put fastboot on PATH."
            )
        return executable

    def _run_fastboot(self, args: List[str], timeout: Optional[int] = None,
                      check: bool = False) -> Tuple[str, str]:
        """Run fastboot and return its stdout and stderr.

        With check off the exit code is ignored, for the listing command where a
        device that is not there is an answer rather than a failure.
        """
        executable = self._require_fastboot()
        try:
            result = subprocess.run(
                [executable] + args,
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False,
                timeout=timeout
            )
        except FileNotFoundError:
            raise FastbootNotFoundError(f"fastboot executable not found at '{executable}'.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"fastboot command timed out: {' '.join(args)}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if check and result.returncode != 0:
            detail = self._sanitize_adb_error(stderr, args[1] if len(args) > 1 else None)
            raise ADBCommandError(f"fastboot failed: {detail or 'unknown error'}")

        return stdout, stderr

    def get_fastboot_devices(self, timeout: Optional[int] = 10) -> List[str]:
        """Serials of the devices currently sitting in fastboot mode.

        adb cannot talk to a fastboot device, so its own device list says
        nothing useful about one. This asks the fastboot binary directly, and
        reports no devices at all when fastboot is not installed, since without
        the tool there is nothing that could be in fastboot mode through here.
        """
        try:
            executable = self._fastboot_executable()
            if not executable:
                return []
            stdout, _ = self._run_fastboot(['devices'], timeout=timeout)
        except (FastbootNotFoundError, ADBCommandError):
            return []
        return _parse_fastboot_devices(stdout)

    def fastboot_reboot(self, device_id: str, timeout: Optional[int] = 30) -> str:
        """Restart a fastboot-mode device back into Android.

        This is the way back out of fastboot: the device leaves fastboot mode and
        comes up as an ordinary adb device. fastboot says nothing at all on
        success, so an empty result is the expected one rather than a failure.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        self._require_fastboot()

        known = self.get_fastboot_devices(timeout=timeout)
        if device_id not in known:
            raise ADBDeviceNotFoundError(
                f"Device '{device_id}' is not in fastboot mode, so it cannot be "
                f"rebooted from there. fastboot currently sees: "
                f"{', '.join(known) if known else 'no devices'}."
            )

        stdout, stderr = self._run_fastboot(['-s', device_id, 'reboot'],
                                            timeout=timeout, check=True)
        return stdout or stderr or f'{device_id} is rebooting'

    def shutdown_device(self, device_id: str) -> str:
        """Power a device off.

        'svc power shutdown' is tried first because it is the tidiest way to ask
        for a power-off, but several Android releases reject the command and exit
        non-zero. 'reboot -p' is the same power-off on those builds.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        try:
            return self._run_command(['shell', 'svc', 'power', 'shutdown'], device_id)
        except ADBCommandError:
            return self._run_command(['reboot', '-p'], device_id)

    def get_root_status(self, device_id: str) -> Dict[str, Any]:
        """Report whether adb itself runs as root and whether an su binary exists.

        An su binary on the device is not proof of access: it may need a prompt
        on the device screen, or be restricted to specific apps.
        """
        status: Dict[str, Any] = {'adb_root': False, 'shell_uid': '', 'su_path': ''}
        try:
            status['shell_uid'] = self._run_command(['shell', 'id', '-u'], device_id).strip()
        except Exception:
            pass
        status['adb_root'] = status['shell_uid'] == '0'

        try:
            su = self._run_command(['shell', 'which', 'su'], device_id).strip()
        except Exception:
            su = ''
        if not su:
            # 'which' is not on every build, so try the usual locations directly.
            try:
                listing = self._run_command(
                    ['shell', 'ls', '/system/xbin/su', '/system/bin/su', '/sbin/su',
                     '/su/bin/su', '/system/sbin/su', '/debug_ramdisk/su'],
                    device_id
                ).strip()
                su = listing.splitlines()[0].strip() if listing else ''
            except Exception:
                su = ''
        status['su_path'] = su
        return status

    def reconnect_devices(self, offline: bool = False) -> str:
        """Ask the adb server to re-establish device connections.

        Args:
            offline: Also drop devices sitting in the 'offline' state

        Returns:
            Output from the adb reconnect command
        """
        args = ['reconnect']
        if offline:
            args.append('offline')
        return self._run_command(args)



def _parse_fastboot_devices(output: str) -> List[str]:
    """The serials of the devices 'fastboot devices' reported.

    The command prints one entry per line and nothing at all when no device is
    in fastboot mode. Builds differ over whether the line carries a state word
    after the serial, so only the first field of each line is taken.
    """
    serials = []
    for line in output.splitlines():
        fields = line.split()
        if fields:
            serials.append(fields[0])
    return serials

