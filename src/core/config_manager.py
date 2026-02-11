import json
import os
from pathlib import Path

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
            'file_manager': {
                'show_hidden': False,
                'use_exact_sizes': False,
                'confirm_rename': True
            },
            'paths': {
                'adb': '',
                'scrcpy': ''
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
                    # Merge loaded settings into defaults
                    self._deep_merge(self.settings, loaded_settings)
            except Exception as e:
                print(f"Error loading config: {e}")
                
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
