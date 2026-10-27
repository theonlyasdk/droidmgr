"""ADBManager mixin: device enumeration, identity, power, fastboot, root."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from .adb_base import ADBCommandError, ADBDeviceNotFoundError, ADBError, FastbootNotFoundError
from .audit_logger import AuditLogger

# Boot/recovery/vendor_boot images all open with the Android boot-image magic.
_BOOT_IMAGE_MAGIC = b'ANDROID!'

# Partitions this tool offers to flash from the Device menu. fastboot routes
# the bare name to the active slot on A/B devices on its own.
_FLASHABLE_BOOT_PARTITIONS = frozenset({'recovery', 'boot'})

# The platform-tools 'x.y.z' build number printed by the adb/fastboot
# version commands. Only three-part numbers count, so the bare protocol
# version ('Android Debug Bridge version 1.0.41') does not match.
_TOOL_VERSION_RE = re.compile(r'\b\d+\.\d+\.\d+\b')


class FastbootFlashError(ADBError):
    """A fastboot flash failed a validation, or was rejected by the device.

    The message gathers every problem found before or during the flash:
    validations first, then the command line, then fastboot's own output.
    """
    pass


def _image_has_boot_magic(path: Path) -> Optional[bool]:
    """Whether a file starts with the boot-image magic; None when unreadable."""
    try:
        with open(path, 'rb') as fh:
            return fh.read(len(_BOOT_IMAGE_MAGIC)) == _BOOT_IMAGE_MAGIC
    except OSError:
        return None


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

    def get_tool_versions(self) -> Dict[str, Any]:
        """The adb and fastboot build versions, read from the binaries.

        adb answers 'Android Debug Bridge version 1.0.41' plus a
        'Version 34.0.5-...' line; fastboot answers 'fastboot version
        34.0.5-...'. Only the shared platform-tools 'x.y.z' is reported,
        since that is the number both tools are supposed to match.

        Each call runs its own short subprocess and remembers nothing, so
        callers should ask rarely (once at startup, from a worker thread).

        Returns:
            {'adb': '<x.y.z>' or None, 'fastboot': '<x.y.z>' or None,
             'adb_ok': bool, 'fastboot_ok': bool}. A tool that is missing,
             could not run, or answered in an unexpected shape reads as None
             with ok False.
        """
        versions: Dict[str, Any] = {'adb': None, 'fastboot': None,
                                    'adb_ok': False, 'fastboot_ok': False}

        try:
            output = self._run_command(['version'], timeout=15)
            versions['adb'] = _extract_tool_version(output)
        except Exception:
            versions['adb'] = None
        versions['adb_ok'] = versions['adb'] is not None

        if self._fastboot_executable():
            try:
                stdout, _ = self._run_fastboot(['--version'], timeout=15)
                versions['fastboot'] = _extract_tool_version(stdout)
            except (FastbootNotFoundError, ADBCommandError, OSError):
                versions['fastboot'] = None
        versions['fastboot_ok'] = versions['fastboot'] is not None

        return versions

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

    def validate_flash_image(self, path: Optional[str],
                             partition: str = 'recovery') -> List[str]:
        """Collect everything that should stop a fastboot flash before it runs.

        The UI calls this as soon as an image is chosen, so every reason not
        to flash can be reported at once instead of one per attempt.

        Returns:
            List of problems, one per line; empty when every check passed
        """
        problems = []
        if partition not in _FLASHABLE_BOOT_PARTITIONS:
            problems.append(
                f"Partition '{partition}' is not one this tool flashes to; "
                "expected 'recovery' or 'boot'.")

        fastboot = self._fastboot_executable()
        if not fastboot:
            problems.append(
                "fastboot was not found. It ships in Android platform-tools "
                "alongside adb; install platform-tools or put fastboot on PATH.")

        if not path:
            problems.append("No image file was chosen.")
            return problems

        image = Path(path)
        try:
            size = image.stat().st_size
            if size <= 0:
                problems.append("The image file is empty (0 bytes).")
            magic = _image_has_boot_magic(image)
            if magic is None:
                problems.append("The image file could not be read (permissions?).")
            elif not magic:
                problems.append(
                    "The image does not start with the Android boot-image magic "
                    "('ANDROID!'), so it is not a recovery, boot or vendor_boot "
                    "image. Verify where the file came from and download it again.")
        except OSError as exc:
            problems.append(f"The image file is not usable: {exc}")
        return problems

    def flash_fastboot_image(self, device_id: str, path: str,
                             partition: str = 'recovery',
                             timeout: Optional[int] = 120) -> str:
        """Write an image to a partition of a device in fastboot mode.

        The image and partition are validated first (the same checks
        validate_flash_image reports), then the device must be visible to
        fastboot, then the full `fastboot -s <serial> flash <partition> <image>`
        command runs. fastboot is often silent on success, so an empty output
        is replaced by this manager's own confirmation.

        Returns:
            fastboot's output, or a written-out confirmation when it is silent
        """
        problems = self.validate_flash_image(path, partition)
        if problems:
            raise FastbootFlashError(
                f"'{path}' cannot be flashed:\n"
                + "\n".join(f"  - {problem}" for problem in problems))

        if not device_id or not device_id.strip():
            raise ValueError("Device serial cannot be empty.")
        self._require_fastboot()

        known = self.get_fastboot_devices()
        if device_id not in known:
            raise ADBDeviceNotFoundError(
                f"Device '{device_id}' is not in fastboot mode, so nothing can be "
                f"flashed to it. fastboot currently sees: "
                f"{', '.join(known) if known else 'no devices'}.")

        executable = self._fastboot_executable()
        image_path = str(Path(path))
        command = [executable, '-s', device_id, 'flash', partition, image_path]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False, timeout=timeout
            )
        except FileNotFoundError as exc:
            AuditLogger.log(device_id, "FASTBOOT_FLASH_FAILED", f"{partition} <- {path}")
            raise FastbootFlashError(
                f"fastboot executable '{executable}' could not be run: {exc}")
        except subprocess.TimeoutExpired:
            AuditLogger.log(device_id, "FASTBOOT_FLASH_FAILED", f"{partition} <- {path}")
            raise FastbootFlashError(
                f"fastboot timed out after {timeout} s while flashing '{image_path}' "
                f"to '{partition}'. The device may still be busy; leave it in "
                "fastboot mode, keep it plugged in, and try again.")

        output = '\n'.join(part for part in (result.stdout.strip(), result.stderr.strip())
                           if part)
        if result.returncode != 0:
            AuditLogger.log(device_id, "FASTBOOT_FLASH_FAILED", f"{partition} <- {path}")
            raise FastbootFlashError(
                f"fastboot rejected the flash (exit code {result.returncode}).\n"
                f"Command: {' '.join(command)}\n"
                f"--- fastboot output ---\n{output or '(no output)'}")

        AuditLogger.log(device_id, "FASTBOOT_FLASH", f"{partition} <- {path}")
        return output or (f"Flashed '{image_path}' to '{partition}' on '{device_id}'.")

    def fastboot_getvar(self, device_id: str, variable: str,
                        timeout: Optional[int] = 15) -> Optional[str]:
        """Value of one fastboot variable ('getvar <name>'), or None.

        fastboot answers on stderr, typically as '( bootloader) name: value'
        with varying spacing of the prefix. The value word is returned when
        the variable is reported; None when nothing readable came back, so
        the caller warns instead of guessing.
        """
        self._require_fastboot()
        stdout, stderr = self._run_fastboot(['-s', device_id, 'getvar', variable],
                                            timeout=timeout)
        return self._parse_getvar_value(f'{stdout}\n{stderr}', variable)

    def fastboot_get_unlock_ability(self, device_id: str,
                                    timeout: Optional[int] = 15) -> Optional[str]:
        """Value of `fastboot flashing get_unlock_ability`, or None.

        '1' means the bootloader can be unlocked from fastboot (OEM unlocking
        has been used/enabled on the device); '0' means it cannot, which is
        worth telling the user about before a flash.
        """
        self._require_fastboot()
        stdout, stderr = self._run_fastboot(
            ['-s', device_id, 'flashing', 'get_unlock_ability'], timeout=timeout)
        return self._parse_getvar_value(f'{stdout}\n{stderr}', 'get_unlock_ability')

    def fastboot_unlocked(self, device_id: str,
                          timeout: Optional[int] = 15) -> Optional[bool]:
        """Whether the device reports an unlocked bootloader (getvar unlocked)."""
        value = self.fastboot_getvar(device_id, 'unlocked', timeout=timeout)
        if value in ('yes', 'true', '1'):
            return True
        if value in ('no', 'false', '0'):
            return False
        return None

    @staticmethod
    def _parse_getvar_value(text: str, variable: str) -> Optional[str]:
        """Pull '<variable>: value' out of getvar-style output, case-blind."""
        needle = f'{variable.lower()}:'
        for line in text.splitlines():
            cleaned = line.lower().replace('(bootloader)', ' ')
            cleaned = cleaned.replace('( bootloader)', ' ').strip()
            if cleaned.startswith(needle):
                value = cleaned[len(needle):].strip()
                return value or None
        return None

    def fastboot_boot(self, device_id: str, image_path: str,
                      timeout: Optional[int] = 120) -> str:
        """Boot a trigger image once from fastboot mode, writing nothing.

        `fastboot boot <img>` runs a boot image from memory — useful to test
        a recovery before committing it to a partition.

        Returns:
            fastboot's output, or a written-out confirmation when it is silent
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device serial cannot be empty.")
        self._require_fastboot()

        image = Path(image_path)
        if not image.exists() or not image.is_file():
            raise FastbootFlashError(f"Image file does not exist: {image_path}")
        if not _image_has_boot_magic(image):
            raise FastbootFlashError(
                f"'{image_path}' does not start with the Android boot-image magic "
                "('ANDROID!'), so it cannot be booted.")

        known = self.get_fastboot_devices(timeout=timeout)
        if device_id not in known:
            raise ADBDeviceNotFoundError(
                f"Device '{device_id}' is not in fastboot mode, so an image cannot "
                f"be booted from there. fastboot currently sees: "
                f"{', '.join(known) if known else 'no devices'}.")

        executable = self._fastboot_executable()
        command = [executable, '-s', device_id, 'boot', str(image)]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False, timeout=timeout
            )
        except FileNotFoundError as exc:
            raise FastbootFlashError(
                f"fastboot executable '{executable}' could not be run: {exc}")
        except subprocess.TimeoutExpired:
            raise FastbootFlashError(
                f"fastboot timed out after {timeout} s booting '{image_path}'. "
                "The device may already have started the image; look at its screen.")

        output = '\n'.join(part for part in (result.stdout.strip(), result.stderr.strip())
                           if part)
        text_upper = output.upper()
        started = 'OKAY' in text_upper or 'BOOTING' in text_upper
        if result.returncode != 0 and not started:
            raise FastbootFlashError(
                f"fastboot rejected the boot (exit code {result.returncode}).\n"
                f"Command: {' '.join(command)}\n"
                f"--- fastboot output ---\n{output or '(no output)'}")

        AuditLogger.log(device_id, "FASTBOOT_BOOT", str(image))
        return output or f"Booted '{image_path}' on '{device_id}' (nothing was written)."

    def validate_sideload_package(self, path: Optional[str]) -> List[str]:
        """Reasons not to sideload the OTA package yet, one per line.

        The device applies the package in one shot, so only cheap local
        checks run here: existence and the zip magic of an OTA package.
        """
        problems = []
        if not path:
            problems.append("No update package was chosen.")
            return problems
        package = Path(path)
        try:
            size = package.stat().st_size
            if size <= 0:
                problems.append("The package file is empty (0 bytes).")
            with open(package, 'rb') as fh:
                magic = fh.read(4)
            if magic != b'PK\x03\x04':
                problems.append(
                    "The package is not a zip archive, so it is not an OTA "
                    "update package; OTA packages are signed zips.")
        except OSError as exc:
            problems.append(f"The package file is not usable: {exc}")
        return problems

    def sideload_package(self, device_id: str, zip_path: str,
                         progress_cb=None) -> str:
        """Apply an OTA zip with `adb sideload`, streaming the percentage.

        adb prints '[ 37%]-...'-style lines while transferring; every
        percentage goes through progress_cb(percent). The callback (if given)
        runs on this thread, which is normally a worker thread. There is no
        timeout by design: a big package is minutes of streaming and only a
        device-side error ends it.

        Returns:
            adb's collected console with the final transfer stats
        """
        package = Path(zip_path)
        if not package.exists() or not package.is_file():
            raise FileNotFoundError(f"Update package does not exist: {zip_path}")
        AuditLogger.log(device_id, "ADB_SIDELOAD", str(package))

        command = [self.adb_path, '-s', device_id, 'sideload', str(package)]
        try:
            proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace')
        except FileNotFoundError as exc:
            AuditLogger.log(device_id, "ADB_SIDELOAD_FAILED", f"{package} ({exc})")
            raise ADBError(f"adb executable '{self.adb_path}' could not be run: {exc}")

        collected: List[str] = []
        percent = 0
        try:
            for line in proc.stdout:
                _line = line.rstrip()
                if not _line:
                    continue
                collected.append(_line)
                if len(collected) > 120:
                    collected = collected[-120:]
                match = re.search(r'\[\s*(\d+)%', _line)
                if match:
                    percent = int(match.group(1))
                    if progress_cb:
                        try:
                            progress_cb(percent)
                        except Exception:
                            pass
            proc.wait()
        except Exception:
            proc.kill()
            proc.wait()
            AuditLogger.log(device_id, "ADB_SIDELOAD_FAILED", str(package))
            raise

        output = '\n'.join(collected)
        if proc.returncode != 0:
            AuditLogger.log(device_id, "ADB_SIDELOAD_FAILED",
                            f"{package} (exit {proc.returncode})")
            raise ADBCommandError(
                f"adb sideload failed (exit code {proc.returncode}); the update "
                "was not applied.\n"
                f"--- adb output ---\n{output or '(no output)'}")
        return output or 'The package was applied.'

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


def _extract_tool_version(output: str) -> Optional[str]:
    """The platform-tools 'x.y.z' inside an adb/fastboot version banner.

    adb also reports the USB protocol version ('Android Debug Bridge version
    1.0.41'), which is not the build number wanted here, so only lines that
    start with the tool's own version banner are considered. None means the
    expected line was missing or carried no three-part number.
    """
    for line in output.splitlines():
        cleaned = line.strip().lower()
        if cleaned.startswith(('version ', 'fastboot version')):
            match = _TOOL_VERSION_RE.search(cleaned)
            if match:
                return match.group(0)
    return None

