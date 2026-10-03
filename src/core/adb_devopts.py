"""ADBManager mixin: developer options and multi-user management."""

import re
from typing import Dict, Any, List, Optional, Tuple


class _DevOptsMixin:
    """_DevOptsMixin for ADBManager (see adb_manager.py)."""

    def get_dev_options(self, device_id: str) -> Dict[str, Any]:
        """Query Developer Options and QA toggles (animation scales, touches, density, etc.)."""
        opts: Dict[str, Any] = {
            'window_animation_scale': '1.0',
            'transition_animation_scale': '1.0',
            'animator_duration_scale': '1.0',
            'show_touches': False,
            'pointer_location': False,
            'stay_awake': False,
            'font_scale': '1.0',
            'night_mode': 'auto',
            'density': '',
            'density_override': '',
            'size': '',
            'size_override': '',
        }
        if not device_id:
            return opts

        try:
            batch_cmd = (
                "echo WIN:$(settings get global window_animation_scale 2>/dev/null); "
                "echo TRANS:$(settings get global transition_animation_scale 2>/dev/null); "
                "echo ANIM:$(settings get global animator_duration_scale 2>/dev/null); "
                "echo TAPS:$(settings get system show_touches 2>/dev/null); "
                "echo PTR:$(settings get system pointer_location 2>/dev/null); "
                "echo AWAKE:$(settings get global stay_on_while_plugged_in 2>/dev/null); "
                "echo FONT:$(settings get system font_scale 2>/dev/null); "
                "echo NIGHT:$(settings get secure ui_night_mode 2>/dev/null); "
                "echo DENSITY:$(wm density 2>/dev/null); "
                "echo SIZE:$(wm size 2>/dev/null)"
            )
            out = self._run_command(['shell', batch_cmd], device_id, timeout=10)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('WIN:'):
                    val = line[4:].strip()
                    if val and val != 'null':
                        opts['window_animation_scale'] = val
                elif line.startswith('TRANS:'):
                    val = line[6:].strip()
                    if val and val != 'null':
                        opts['transition_animation_scale'] = val
                elif line.startswith('ANIM:'):
                    val = line[5:].strip()
                    if val and val != 'null':
                        opts['animator_duration_scale'] = val
                elif line.startswith('TAPS:'):
                    opts['show_touches'] = line[5:].strip() == '1'
                elif line.startswith('PTR:'):
                    opts['pointer_location'] = line[4:].strip() == '1'
                elif line.startswith('AWAKE:'):
                    val = line[6:].strip()
                    try:
                        opts['stay_awake'] = int(val) > 0
                    except (ValueError, TypeError):
                        opts['stay_awake'] = False
                elif line.startswith('FONT:'):
                    val = line[5:].strip()
                    if val and val != 'null':
                        opts['font_scale'] = val
                elif line.startswith('NIGHT:'):
                    val = line[6:].strip()
                    if val in ('2', 'yes'):
                        opts['night_mode'] = 'dark'
                    elif val in ('1', 'no'):
                        opts['night_mode'] = 'light'
                    else:
                        opts['night_mode'] = 'auto'
                elif line.startswith('DENSITY:'):
                    # Batch line looks like "DENSITY:Physical density: 320":
                    # strip our own marker first, or split(':', 1) eats it
                    # and the entry ends up holding "Physical density: 320".
                    payload = line[len('DENSITY:'):].strip()
                    if 'Override density:' in payload:
                        opts['density_override'] = payload.split('Override density:', 1)[1].strip()
                    elif 'Physical density:' in payload:
                        opts['density'] = payload.split('Physical density:', 1)[1].strip()
                elif 'density:' in line.lower():
                    # Continuation line from multi-line `wm density` output.
                    if 'Override density:' in line:
                        opts['density_override'] = line.split('Override density:', 1)[1].strip()
                    elif 'Physical density:' in line:
                        opts['density'] = line.split('Physical density:', 1)[1].strip()
                elif line.startswith('SIZE:'):
                    payload = line[len('SIZE:'):].strip()
                    if 'Override size:' in payload:
                        opts['size_override'] = payload.split('Override size:', 1)[1].strip()
                    elif 'Physical size:' in payload:
                        opts['size'] = payload.split('Physical size:', 1)[1].strip()
                elif 'size:' in line.lower():
                    # Continuation line from multi-line `wm size` output.
                    if 'Override size:' in line:
                        opts['size_override'] = line.split('Override size:', 1)[1].strip()
                    elif 'Physical size:' in line:
                        opts['size'] = line.split('Physical size:', 1)[1].strip()
        except Exception:
            pass

        return opts

    def set_dev_option(self, device_id: str, key: str, value: Any) -> Tuple[bool, str]:
        """Apply a Developer Option / QA toggle on the device.

        Returns (success: bool, error_or_output_msg: str).
        """
        if not device_id:
            return False, "No device selected."

        cmd = ""
        if key == 'window_animation_scale':
            cmd = f"settings put global window_animation_scale {value}"
        elif key == 'transition_animation_scale':
            cmd = f"settings put global transition_animation_scale {value}"
        elif key == 'animator_duration_scale':
            cmd = f"settings put global animator_duration_scale {value}"
        elif key == 'all_animation_scales':
            cmd = (
                f"settings put global window_animation_scale {value}; "
                f"settings put global transition_animation_scale {value}; "
                f"settings put global animator_duration_scale {value}"
            )
        elif key == 'show_touches':
            v = '1' if value else '0'
            cmd = f"settings put system show_touches {v}"
        elif key == 'pointer_location':
            v = '1' if value else '0'
            cmd = f"settings put system pointer_location {v}"
        elif key == 'stay_awake':
            v = '7' if value else '0'
            cmd = f"settings put global stay_on_while_plugged_in {v}"
        elif key == 'font_scale':
            cmd = f"settings put system font_scale {value}"
        elif key == 'night_mode':
            if str(value).lower() in ('dark', 'yes', '2', 'true'):
                cmd = "cmd uimode night yes; settings put secure ui_night_mode 2"
            elif str(value).lower() in ('light', 'no', '1', 'false'):
                cmd = "cmd uimode night no; settings put secure ui_night_mode 1"
            else:
                cmd = "cmd uimode night auto; settings put secure ui_night_mode 0"
        elif key == 'density':
            if str(value).lower() == 'reset':
                cmd = "wm density reset"
            else:
                cmd = f"wm density {value}"
        elif key == 'size':
            if str(value).lower() == 'reset':
                cmd = "wm size reset"
            else:
                cmd = f"wm size {value}"
        else:
            return False, f"Unknown developer option key: '{key}'"

        try:
            out = self._run_command(['shell', cmd], device_id, timeout=10)
            lowered = out.lower()
            if 'securityexception' in lowered or 'permission denial' in lowered or 'write_secure_settings' in lowered:
                return False, (
                    "Permission Denial: Writing system settings via ADB requires enabling "
                    "'USB debugging (Security settings)' in Developer Options on your phone "
                    "(common on Xiaomi/MIUI/realme), or granting WRITE_SECURE_SETTINGS via ADB."
                )
            if 'error' in lowered or 'exception' in lowered:
                return False, out.strip() or "Failed to update setting"
            return True, "OK"
        except Exception as ex:
            return False, str(ex)

    def get_users(self, device_id: str) -> List[Dict[str, Any]]:
        """List Android user profiles (pm list users, am get-current-user)."""
        users: List[Dict[str, Any]] = []
        if not device_id:
            return users
        try:
            out = self._run_command(['shell', 'pm list users; echo CURRENT:$(am get-current-user 2>/dev/null)'], device_id, timeout=10)
            current_id = None
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('CURRENT:'):
                    current_id = line.split(':', 1)[1].strip()

            user_pattern = re.compile(r'UserInfo\{(\d+):([^:]+):([0-9a-fA-Fx]+)\}(.*)')
            for line in out.splitlines():
                line = line.strip()
                m = user_pattern.search(line)
                if m:
                    u_id, u_name, u_flags, rest = m.groups()
                    is_running = 'running' in rest.lower()
                    is_current = (u_id == current_id)
                    users.append({
                        'id': u_id,
                        'name': u_name,
                        'flags': u_flags,
                        'running': is_running,
                        'current': is_current,
                        'raw': line
                    })
        except Exception:
            pass
        return users

    def switch_user(self, device_id: str, user_id: str) -> Tuple[bool, str]:
        """Switch active user via am switch-user."""
        if not device_id:
            return False, "No device selected."
        try:
            out = self._run_command(['shell', f'am switch-user {user_id}'], device_id, timeout=10)
            if 'error' in out.lower() or 'exception' in out.lower():
                return False, out.strip()
            return True, "Switched user successfully."
        except Exception as ex:
            return False, str(ex)

    def create_user(self, device_id: str, name: str, user_type: str = 'standard') -> Tuple[bool, str]:
        """Create new user profile (pm create-user).
        user_type can be 'standard', 'guest', or 'managed' (work profile).
        """
        if not device_id:
            return False, "No device selected."
        name = name.strip()
        if not name:
            return False, "User name cannot be empty."
        flags = ""
        if user_type == 'guest':
            flags = "--guest "
        elif user_type == 'managed':
            flags = "--profileOf 0 --managed "
        
        try:
            out = self._run_command(['shell', f'pm create-user {flags}"{name}"'], device_id, timeout=15)
            if 'success' in out.lower():
                return True, out.strip()
            return False, out.strip() or "Failed to create user."
        except Exception as ex:
            return False, str(ex)

    def remove_user(self, device_id: str, user_id: str) -> Tuple[bool, str]:
        """Remove a user profile via pm remove-user."""
        if not device_id:
            return False, "No device selected."
        if str(user_id) == '0':
            return False, "Cannot remove primary owner (User 0)."
        try:
            out = self._run_command(['shell', f'pm remove-user {user_id}'], device_id, timeout=15)
            if 'success' in out.lower():
                return True, out.strip()
            return False, out.strip() or f"Failed to remove user {user_id}."
        except Exception as ex:
            return False, str(ex)

