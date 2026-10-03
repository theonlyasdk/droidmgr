"""Persisting scrcpy settings to the config file."""


class SaveSettingsMixin:
    def _on_save(self):
        try:
            max_size_val = self.max_size_cb.get().split()[0]
            max_size = int(max_size_val)
        except (ValueError, IndexError):
            max_size = 0
            
        try:
            max_fps_val = self.max_fps_cb.get().split()[0]
            max_fps = int(max_fps_val)
        except (ValueError, IndexError):
            max_fps = 0
            
        try:
            angle = int(self.angle_var.get())
        except ValueError:
            angle = 0
            
        try:
            audio_buffer = int(self.audio_buffer_var.get())
        except ValueError:
            audio_buffer = 50

        try:
            cam_fps = int(self.camera_fps_var.get())
        except ValueError:
            cam_fps = 0
            
        # Update config directly
        self.config.set('scrcpy', 'video_bit_rate', self.video_bitrate_var.get())
        self.config.set('scrcpy', 'video_codec', self.video_codec_var.get())
        self.config.set('scrcpy', 'audio_bit_rate', self.audio_bitrate_var.get())
        self.config.set('scrcpy', 'audio_codec', self.audio_codec_var.get())
        self.config.set('scrcpy', 'audio_source', self.audio_source_var.get())
        self.config.set('scrcpy', 'audio_buffer', audio_buffer)
        self.config.set('scrcpy', 'angle', angle)
        self.config.set('scrcpy', 'max_size', max_size if max_size > 0 else None)
        self.config.set('scrcpy', 'max_fps', max_fps if max_fps > 0 else 0)
        self.config.set('scrcpy', 'mouse_mode', self.mouse_mode_var.get())
        self.config.set('scrcpy', 'window_title', self.window_title_var.get())
        
        # Checkboxes
        for key, var in self.check_vars.items():
            self.config.set('scrcpy', key, var.get())
            
        # Video/Camera
        self.config.set('scrcpy', 'video_source', self.video_source_var.get())
        self.config.set('scrcpy', 'camera_id', self.camera_id_var.get())
        self.config.set('scrcpy', 'camera_facing', self.camera_facing_var.get())
        self.config.set('scrcpy', 'camera_ar', self.camera_ar_var.get())
        self.config.set('scrcpy', 'camera_fps', cam_fps)
        self.config.set('scrcpy', 'camera_size', self.camera_size_var.get())
        
        self.config.set('scrcpy', 'no_audio', self.no_audio_var.get())
        self.config.set('scrcpy', 'no_video', self.no_video_var.get())
        
        # Controls
        self.config.set('scrcpy', 'keyboard_mode', self.keyboard_mode_var.get())
        self.config.set('scrcpy', 'no_control', self.no_control_var.get())
        self.config.set('scrcpy', 'no_clipboard_autosync', self.no_clipboard_autosync_var.get())
        self.config.set('scrcpy', 'no_key_repeat', self.no_key_repeat_var.get())
        self.config.set('scrcpy', 'no_mouse_hover', self.no_mouse_hover_var.get())
        self.config.set('scrcpy', 'no_power_on', self.no_power_on_var.get())
        self.config.set('scrcpy', 'otg', self.otg_var.get())
        
        # Record
        self.config.set('scrcpy', 'record', self.record_var.get())
        path = self.record_path_var.get()
        if path == self.placeholder:
            path = ""
        self.config.set('scrcpy', 'record_path', path)
        
        self.config.save()
        
        self.result = True
        self.destroy()
