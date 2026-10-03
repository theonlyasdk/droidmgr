"""ADBManager foundation: init, command runners, shared errors."""

import re
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


class FastbootNotFoundError(RuntimeError):
    """Raised when the fastboot executable cannot be found."""
    pass


class _ADBBase:
    """_ADBBase for ADBManager (see adb_manager.py)."""

    def __init__(self, adb_path: Path):
        self.adb_path = str(adb_path)
        self._fastboot_path: Optional[str] = None

    @staticmethod
    def _sanitize_adb_error(err_text: str, device_id: Optional[str] = None) -> str:
        if not err_text:
            return ""
        # Strip ANSI escape sequences
        text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', err_text)
        # Redact device serial if present
        if device_id and device_id in text:
            text = text.replace(device_id, '[REDACTED_SERIAL]')
        text = text.strip()
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    def _run_command(self, args: List[str], device_id: Optional[str] = None,
                     timeout: Optional[int] = None) -> str:
        cmd = [self.adb_path]
        
        if device_id:
            cmd.extend(['-s', device_id])
        
        cmd.extend(args)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=True,
                timeout=timeout
            )
            return result.stdout.strip()
        except FileNotFoundError:
            raise ADBNotFoundError(f"ADB executable not found at '{self.adb_path}'. Please verify the path in Preferences > External Tools.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"ADB command timed out: {' '.join(args)}")
        except subprocess.CalledProcessError as e:

            stderr = e.stderr.strip() if e.stderr else (e.stdout.strip() if e.stdout else str(e))
            clean_err = self._sanitize_adb_error(stderr, device_id)
            
            lower_err = stderr.lower()
            if 'device not found' in lower_err or 'no devices/emulators found' in lower_err:
                raise ADBDeviceNotFoundError(f"Device not found or disconnected: {clean_err}")
            elif 'device offline' in lower_err or 'device unauthorized' in lower_err:
                raise ADBDeviceOfflineError(f"Device is offline or unauthorized: {clean_err}")
            else:
                raise ADBCommandError(f"ADB command failed: {clean_err}")

    def _run_exec_out(self, args: List[str], device_id: str, timeout: int = 60) -> bytes:
        """Run a device command and return raw stdout bytes (for APK zip entries)."""
        cmd = [self.adb_path, '-s', device_id, 'exec-out'] + args
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise ADBNotFoundError(
                f"ADB executable not found at '{self.adb_path}'. "
                "Please verify the path in Preferences > External Tools."
            )
        except subprocess.TimeoutExpired:
            raise ADBCommandError("ADB command timed out.")
        if result.returncode != 0 and not result.stdout:
            stderr = ''
            if result.stderr:
                stderr = result.stderr.decode('utf-8', errors='replace')
            raise ADBCommandError(
                f"ADB command failed: {self._sanitize_adb_error(stderr, device_id)}"
            )
        return result.stdout

    def _run_probe(self, args: List[str], device_id: Optional[str] = None,
                   timeout: Optional[int] = None) -> Tuple[str, str]:
        """Run a command and return its stdout and stderr, exit code ignored.

        Diagnostic commands report their findings by failing: an unreachable host
        is the answer to a ping, not a broken command, so raising on a non-zero
        exit would throw away the only useful part of the run.
        """
        cmd = [self.adb_path]
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                check=False, timeout=timeout
            )
        except FileNotFoundError:
            raise ADBNotFoundError(f"ADB executable not found at '{self.adb_path}'. Please verify the path in Preferences > External Tools.")
        except subprocess.TimeoutExpired:
            raise ADBCommandError(f"ADB command timed out: {' '.join(args)}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # A device that has gone away still fails the command, and that one
        # failure is worth the friendly message rather than a raw exit code.
        lower = (stderr or stdout).lower()
        if 'device not found' in lower or 'no devices/emulators found' in lower:
            raise ADBDeviceNotFoundError(f"Device not found or disconnected: {stderr}")
        if 'device offline' in lower or 'device unauthorized' in lower:
            raise ADBDeviceOfflineError(f"Device is offline or unauthorized: {stderr}")

        return stdout, stderr



class ADBError(RuntimeError):
    """Base exception for ADB operations."""
    pass

class ADBNotFoundError(ADBError):
    """Raised when the ADB executable is not found on PATH or specified location."""
    pass

class ADBDeviceNotFoundError(ADBError):
    """Raised when a specified device is not found or disconnected."""
    pass


class ADBDeviceOfflineError(ADBError):
    """Raised when the target device is offline or unauthorized."""
    pass

class ADBCommandError(ADBError):
    """Raised when an ADB command fails execution."""
    pass
