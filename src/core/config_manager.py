import json
import os
from pathlib import Path

CURRENT_CONFIG_VERSION = 2
DEFAULT_BACKUP_EXCLUSIONS = ['/storage/emulated/0/Android']
DEFAULT_SHELL_PRESETS = [
    {'name': 'Battery', 'command': 'dumpsys battery'},
    {'name': 'IP Address', 'command': 'ip addr'},
    {'name': 'Properties', 'command': 'getprop'},
]
# Android's screenrecord refuses to record for longer than this.
MAX_RECORD_SECONDS = 180


class ConfigManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
        
    def __init__(self):
        if self._initialized: return
        
        self.config_dir = Path.home() / '.droidmgr'
        self.config_file = self.config_dir / 'config.json'
        
        # Default settings
        self.settings = {
            'config_version': CURRENT_CONFIG_VERSION,
            'general': {
                'query_interval': 5,
                'apps_view_mode': 'compact'
            },
            'file_manager': {
                'show_hidden': False,
                'use_exact_sizes': False,
                'confirm_rename': True
            },
            'backup': {
                'exclude_paths': list(DEFAULT_BACKUP_EXCLUSIONS),
                'scope': 0,
                'parallelism': 4,
                'verify_checksums': False,
            },
            'paths': {
                'adb': '',
                'scrcpy': ''
            },
            'shell': {
                'presets': [dict(p) for p in DEFAULT_SHELL_PRESETS],
            },
            'capture': {
                'screenshot_dir': '',
                'record_dir': '',
                'apk_dir': '',
                'record_time_limit': 30,
                'record_bit_rate': '',
                'record_size': '',
            },
            'scrcpy': {
                'video_bit_rate': '8M',
                'audio_bit_rate': '128K',
                'max_size': None,
                'max_fps': 0,
                'fullscreen': False,
                'always_on_top': False,
                'stay_awake': False,
                'turn_screen_off': False,
                'no_audio': False,
                'no_video': False,
                'show_touches': False,
                'window_borderless': False,
                'orientation': '0',
                'window_title': 'Droidmgr Mirroring',
                'video_codec': 'h264',
                'audio_codec': 'opus',
                'power_off_on_close': False,
                'mouse_mode': 'sdk',
                'angle': 0,
                'audio_buffer': 50,
                'audio_source': 'output',
                'video_source': 'display',
                'camera_id': '',
                'camera_facing': 'any',
                'camera_ar': '',
                'camera_fps': 0,
                'camera_size': '',
                'keyboard_mode': 'sdk',
                'no_control': False,
                'no_clipboard_autosync': False,
                'no_key_repeat': False,
                'no_mouse_hover': False,
                'no_power_on': False,
                'otg': False,
                'print_fps': False,
                'record': False,
                'record_path': ''
            }
        }
        
        self.load()
        self._initialized = True
        
    def load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded_settings = json.load(f)
                    
                    # Version check and migration
                    loaded_version = loaded_settings.get('config_version', 0)
                    if loaded_version < CURRENT_CONFIG_VERSION:
                        loaded_settings = self._migrate(loaded_settings, loaded_version)
                        
                    # Merge loaded settings into defaults
                    self._deep_merge(self.settings, loaded_settings)
            except Exception as e:
                print(f"Error loading config: {e}")
        self._validate()

    def _migrate(self, settings: dict, from_version: int) -> dict:
        """Migrate configuration settings from older schema versions."""
        print(f"Migrating config schema from version {from_version} to {CURRENT_CONFIG_VERSION}")
        if from_version < 1:
            general = settings.setdefault('general', {})
            general.setdefault('query_interval', 5)
            general.setdefault('apps_view_mode', 'compact')
        if from_version < 2:
            backup = settings.setdefault('backup', {})
            if not backup.get('exclude_paths'):
                backup['exclude_paths'] = list(DEFAULT_BACKUP_EXCLUSIONS)
        settings['config_version'] = CURRENT_CONFIG_VERSION
        return settings

    def _validate(self):

        """Validate loaded configuration values and revert invalid fields to defaults."""
        # Validate query_interval (must be int/float between 1 and 300)
        try:
            val = self.settings.get('general', {}).get('query_interval')
            if val is None or not isinstance(val, (int, float)) or val < 1 or val > 300:
                print(f"Warning: Invalid query_interval {val!r} in config. Reverting to default 5.")
                self.settings.setdefault('general', {})['query_interval'] = 5
        except Exception:
            self.settings.setdefault('general', {})['query_interval'] = 5

        # Validate apps_view_mode (must be 'compact' or 'detailed')
        try:
            val = self.settings.get('general', {}).get('apps_view_mode')
            if val not in ('compact', 'detailed'):
                print(f"Warning: Invalid apps_view_mode {val!r} in config. Reverting to default 'compact'.")
                self.settings.setdefault('general', {})['apps_view_mode'] = 'compact'
        except Exception:
            self.settings.setdefault('general', {})['apps_view_mode'] = 'compact'

        backup = self.settings.setdefault('backup', {})
        if backup.get('scope') not in (0, 1):
            backup['scope'] = 0
        if backup.get('parallelism') not in (1, 2, 4, 8):
            backup['parallelism'] = 4
        if not isinstance(backup.get('verify_checksums'), bool):
            backup['verify_checksums'] = False
        if not isinstance(backup.get('exclude_paths'), list):
            backup['exclude_paths'] = list(DEFAULT_BACKUP_EXCLUSIONS)

        # Validate paths (must be strings)
        for path_key in ('adb', 'scrcpy'):
            try:
                val = self.settings.get('paths', {}).get(path_key)
                if val is not None and not isinstance(val, str):
                    print(f"Warning: Invalid path type for '{path_key}': {val!r}. Reverting to empty string.")
                    self.settings.setdefault('paths', {})[path_key] = ''
            except Exception:
                self.settings.setdefault('paths', {})[path_key] = ''

        # Validate shell presets (list of {'name': str, 'command': str})
        shell = self.settings.setdefault('shell', {})
        presets = shell.get('presets')
        if not isinstance(presets, list):
            print("Warning: Invalid shell.presets in config. Reverting to defaults.")
            presets = list(DEFAULT_SHELL_PRESETS)
        cleaned = []
        for item in presets:
            if isinstance(item, dict):
                name = item.get('name')
                command = item.get('command')
                if isinstance(name, str) and isinstance(command, str) and name.strip() and command.strip():
                    cleaned.append({'name': name, 'command': command})
            else:
                print(f"Warning: Dropping malformed shell preset {item!r}.")
        shell['presets'] = cleaned

        # Validate capture settings (screenshot/recording defaults)
        capture = self.settings.setdefault('capture', {})
        for key in ('screenshot_dir', 'record_dir', 'apk_dir', 'record_bit_rate', 'record_size'):
            if not isinstance(capture.get(key), str):
                capture[key] = ''
        try:
            limit = capture.get('record_time_limit')
            if isinstance(limit, bool) or not isinstance(limit, (int, float)):
                raise ValueError
            capture['record_time_limit'] = max(1, min(int(limit), MAX_RECORD_SECONDS))
        except (TypeError, ValueError):
            print("Warning: Invalid capture.record_time_limit in config. Reverting to default 30.")
            capture['record_time_limit'] = 30


    def _deep_merge(self, base, update):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
                
    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
            
    def get(self, section, key, default=None):
        return self.settings.get(section, {}).get(key, default)
        
    def set(self, section, key, value):
        if section not in self.settings:
            self.settings[section] = {}
        self.settings[section][key] = value
        self.save()
