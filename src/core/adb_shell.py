"""ADBManager mixin: logcat, interactive shell, capture and input."""

import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple
from .adb_base import ADBError, ADBNotFoundError, ADBCommandError


class _ShellMixin:
    """_ShellMixin for ADBManager (see adb_manager.py)."""

    def get_logcat(self, device_id: str) -> subprocess.Popen:
        """Start streaming `adb logcat -v brief` for a device.

        Args:
            device_id: Device ID / serial number

        Returns:
            A running subprocess.Popen with line-buffered text stdout.
            Caller is responsible for terminating the process.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        cmd = [self.adb_path, '-s', device_id, 'logcat', '-v', 'brief']
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )
        return process

    def clear_logcat(self, device_id: str) -> None:
        """Clear the on-device logcat buffers (`adb logcat -c`)."""
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        self._run_command(['logcat', '-c'], device_id)

    def run_shell_command(self, device_id: str, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """Run a single shell command on a device and return (returncode, stdout, stderr).

        The whole command string is handed to the device shell verbatim, so pipes,
        redirections and quoting work as typed. Unlike `_run_command`, a non-zero exit
        status is reported as a result instead of raised, because shell utilities such
        as `grep` fail legitimately and the caller shows the exit code inline.

        Args:
            device_id: Device ID / serial number
            command: Command line to run through the device shell
            timeout: Seconds to wait before giving up

        Returns:
            Tuple of (returncode, stdout, stderr). stderr carries the sanitized
            ADB error message when the command failed.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        if not command or not command.strip():
            return 0, '', ''
        try:
            stdout = self._run_command(['shell', command], device_id, timeout=timeout)
            return 0, stdout, ''
        except ADBCommandError as exc:
            # A failed shell command is data, not a control-flow error: the device
            # itself is reachable, it just returned non-zero (or timed out).
            return 1, '', str(exc)

    def start_shell_session(self, device_id: str, allocate_tty: bool = True) -> subprocess.Popen:
        """Start an interactive `adb shell` session for a device.

        Args:
            device_id: Device ID / serial number
            allocate_tty: Request a pty (`-t`) so the device shell behaves
                interactively. Disable for adb builds that reject the flag.

        Returns:
            A running subprocess.Popen with pipes attached to stdin/stdout and
            stderr merged into stdout (as a terminal would).
            Caller is responsible for terminating the process.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        cmd = [self.adb_path, '-s', device_id, 'shell']
        if allocate_tty:
            cmd.append('-t')
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )

    def capture_screenshot(self, device_id: str) -> bytes:
        """Capture the current screen as PNG bytes (`adb exec-out screencap -p`).

        Uses exec-out so the raw PNG stream is returned untouched, with no CRLF
        translation that would corrupt the image.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        data = self._run_exec_out(['screencap', '-p'], device_id, timeout=30)
        if not data.startswith(b'\x89PNG'):
            raise ADBCommandError(
                "Screen capture did not return a PNG image. "
                "The device may have refused the request."
            )
        return data

    def start_screenrecord(self, device_id: str, remote_path: str, time_limit: int = 180,
                           bit_rate: Optional[str] = None,
                           size: Optional[str] = None) -> subprocess.Popen:
        """Start `adb shell screenrecord`, writing the video to a device path.

        Args:
            device_id: Device ID / serial number
            remote_path: Absolute on-device path for the .mp4 file
            time_limit: Maximum duration in seconds (Android caps this at 180)
            bit_rate: Video bit rate (e.g. '8M'); device default when omitted
            size: Size limit as WIDTHxHEIGHT (e.g. '1280x720'); device default when omitted

        Returns:
            A running subprocess.Popen. The recording keeps going until the time
            limit is reached, or until stop_screenrecord() finalizes it.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        if not remote_path or not remote_path.strip():
            raise ValueError("Remote recording path cannot be empty.")

        args = ['shell', 'screenrecord']
        if time_limit:
            args.extend(['--time-limit', str(int(time_limit))])
        if bit_rate:
            args.extend(['--bit-rate', str(bit_rate)])
        if size:
            args.extend(['--size', str(size)])
        args.append(remote_path)

        cmd = [self.adb_path, '-s', device_id] + args
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )

    def stop_screenrecord(self, device_id: str) -> bool:
        """Ask an on-device screenrecord to stop so it finalizes the MP4.

        Terminating the local adb client would leave the device-side encoder
        running and the file unfinalized, so SIGINT is sent to the device process
        instead. screenrecord flushes and closes the file on SIGINT.

        Returns:
            True when the signal was delivered, False when the device-side
            process could not be found or signalled.
        """
        if not device_id or not device_id.strip():
            raise ValueError("Device ID cannot be empty.")
        try:
            output = self._run_command(['shell', 'pidof screenrecord'], device_id)
        except ADBError:
            return False
        pids = [token for token in output.split() if token.isdigit()]
        if not pids:
            return False
        try:
            self._run_command(['shell', 'kill', '-INT'] + pids, device_id)
        except ADBError:
            return False
        return True

    def send_keyevent(self, device_id: str, keycode: int) -> bool:
        """Send an Android keyevent to the device."""
        try:
            self._run_command(['shell', 'input', 'keyevent', str(keycode)], device_id, timeout=8)
            return True
        except Exception:
            return False

    def send_text(self, device_id: str, text: str) -> bool:
        """Send text input to the device via adb shell input text."""
        try:
            escaped = text.replace(' ', '%s').replace('&', '\\&').replace('"', '\\"').replace("'", "\\'")
            self._run_command(['shell', 'input', 'text', escaped], device_id, timeout=8)
            return True
        except Exception:
            return False

    def set_clipboard_text(self, device_id: str, text: str) -> bool:
        """Set device clipboard text via cmd clipboard set-text."""
        try:
            self._run_command(['shell', 'cmd', 'clipboard', 'set-text', text], device_id, timeout=8)
            return True
        except Exception:
            return False

    def rotate_display(self, device_id: str) -> int:
        """Rotate screen orientation to the next 90-degree step."""
        try:
            cur = self._run_command(['shell', 'settings', 'get', 'system', 'user_rotation'], device_id, timeout=8).strip()
            val = int(cur) if cur.isdigit() else 0
            nxt = (val + 1) % 4
            self._run_command(['shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'], device_id, timeout=8)
            self._run_command(['shell', 'settings', 'put', 'system', 'user_rotation', str(nxt)], device_id, timeout=8)
            return nxt
        except Exception:
            return 0

