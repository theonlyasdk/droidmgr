"""Audio settings for the scrcpy settings dialog."""

import tkinter as tk
from tkinter import ttk


class AudioSettingsMixin:
    def _create_audio_settings(self):
        self.audio_tab.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(self.audio_tab, text="Audio Bitrate:").grid(row=row, column=0, sticky='w', pady=5)
        self.audio_bitrate_var = tk.StringVar(value=self.config.get('scrcpy', 'audio_bit_rate', '128K'))
        self.audio_bitrate_cb = ttk.Combobox(self.audio_tab, textvariable=self.audio_bitrate_var, values=['64K', '96K', '128K', '192K', '256K'])
        self.audio_bitrate_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.audio_bitrate_cb, "Set the audio bit rate (e.g., 128K).")
        row += 1
        
        ttk.Label(self.audio_tab, text="Audio Codec:").grid(row=row, column=0, sticky='w', pady=5)
        self.audio_codec_var = tk.StringVar(value=self.config.get('scrcpy', 'audio_codec', 'opus'))
        self.audio_codec_cb = ttk.Combobox(self.audio_tab, textvariable=self.audio_codec_var, values=['opus', 'aac', 'flac', 'raw'], state='readonly')
        self.audio_codec_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.audio_codec_cb, "Select audio codec (opus is recommended).")
        row += 1
        
        ttk.Label(self.audio_tab, text="Audio Source:").grid(row=row, column=0, sticky='w', pady=5)
        self.audio_source_var = tk.StringVar(value=self.config.get('scrcpy', 'audio_source', 'output'))
        self.audio_source_cb = ttk.Combobox(self.audio_tab, textvariable=self.audio_source_var, values=['output', 'playback', 'mic'], state='readonly')
        self.audio_source_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.audio_source_cb, "Select audio source to capture.")
        row += 1
        
        ttk.Label(self.audio_tab, text="Buffer (ms):").grid(row=row, column=0, sticky='w', pady=5)
        self.audio_buffer_var = tk.StringVar(value=str(self.config.get('scrcpy', 'audio_buffer', 50)))
        ab_spin = ttk.Spinbox(self.audio_tab, from_=5, to=1000, textvariable=self.audio_buffer_var)
        ab_spin.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(ab_spin, "Audio buffer delay (in milliseconds).")
        row += 1
        
        self.no_audio_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_audio', False))
        na_chk = ttk.Checkbutton(self.audio_tab, text="Disable Audio Forwarding (--no-audio)", variable=self.no_audio_var)
        na_chk.grid(row=row, column=0, columnspan=2, sticky='w', pady=10)
        self._add_tooltip(na_chk, "Do not forward audio from the device.")
