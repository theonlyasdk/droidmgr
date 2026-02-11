"""Manages scrcpy processes for screen mirroring."""

import subprocess
from pathlib import Path
from typing import Optional, Dict
import signal
import os


class ScrcpyManager:
    """Manages scrcpy screen mirroring sessions."""
    
    def __init__(self, scrcpy_path: Path):
        """Initialize the scrcpy manager.
        
        Args:
            scrcpy_path: Path to the scrcpy executable
        """
        self.scrcpy_path = str(scrcpy_path)
        self.active_sessions: Dict[str, subprocess.Popen] = {}
    
    def start_mirroring(
        self,
        device_id: str,
        video_bit_rate: str = '8M',
        audio_bit_rate: str = '128K',
        max_size: Optional[int] = None,
        fullscreen: bool = False,
        always_on_top: bool = False,
        stay_awake: bool = False,
        turn_screen_off: bool = False,
        no_audio: bool = False,
        no_video: bool = False,
        max_fps: int = 0,
        orientation: str = '0',
        window_title: Optional[str] = None,
        video_codec: str = 'h264',
        audio_codec: str = 'opus',
        power_off_on_close: bool = False,
        show_touches: bool = False,
        window_borderless: bool = False,
        mouse_mode: str = 'sdk',
        angle: int = 0,
        audio_buffer: int = 50,
        audio_source: str = 'output',
        video_source: str = 'display',
        camera_id: Optional[str] = None,
        camera_facing: Optional[str] = None,
        camera_ar: Optional[str] = None,
        camera_fps: int = 0,
        camera_size: Optional[str] = None,
        keyboard_mode: str = 'sdk',
        no_control: bool = False,
        no_clipboard_autosync: bool = False,
        no_key_repeat: bool = False,
        no_mouse_hover: bool = False,
        no_power_on: bool = False,
        otg: bool = False,
        print_fps: bool = False,
        record_path: Optional[str] = None
    ) -> subprocess.Popen:
        """Start screen mirroring for a device.
        
        Args:
            device_id: Device ID to mirror
            video_bit_rate: Video bit rate (e.g., '8M')
            audio_bit_rate: Audio bit rate (e.g., '128K')
            max_size: Maximum screen dimension
            fullscreen: Start in fullscreen mode
            always_on_top: Keep window always on top
            stay_awake: Prevent device from sleeping
            turn_screen_off: Turn device screen off during mirroring
            no_audio: Disable audio forwarding
            no_video: Disable video forwarding
            max_fps: Limit frame rate
            orientation: Screen orientation (0, 90, 180, 270)
            window_title: Custom window title
            video_codec: Video codec (h264, h265, av1)
            audio_codec: Audio codec (opus, aac, flac, raw)
            power_off_on_close: Power off device on close
            show_touches: Show physical touches
            window_borderless: Borderless window
            mouse_mode: Mouse mode (sdk, uhid, aoa, disabled)
            angle: Custom rotation angle in degrees
            audio_buffer: Audio buffer delay in ms
            audio_source: Audio source (output, playback, mic, etc.)
            
        Returns:
            The scrcpy process instance
        """
        if device_id in self.active_sessions:
            raise RuntimeError(f"Mirroring already active for device {device_id}")
        
        cmd = [self.scrcpy_path, '-s', device_id]
        
        if not no_video:
            cmd.extend(['--video-bit-rate', video_bit_rate])
        else:
            cmd.append('--no-video')
            
        if not no_audio:
            cmd.extend(['--audio-bit-rate', audio_bit_rate])
        else:
            cmd.append('--no-audio')
        
        if max_size:
            cmd.extend(['--max-size', str(max_size)])
        
        if fullscreen:
            cmd.append('--fullscreen')
        
        if always_on_top:
            cmd.append('--always-on-top')

        if stay_awake:
            cmd.append('--stay-awake')
        
        if turn_screen_off:
            cmd.append('--turn-screen-off')
            
        if max_fps > 0:
            cmd.extend(['--max-fps', str(max_fps)])
            
        if orientation != '0':
            cmd.extend(['--orientation', orientation])
            
        if window_title:
            cmd.extend(['--window-title', window_title])
            
        if video_codec != 'h264':
            cmd.extend(['--video-codec', video_codec])
            
        if audio_codec != 'opus':
            cmd.extend(['--audio-codec', audio_codec])
            
        if power_off_on_close:
            cmd.append('--power-off-on-close')
            
        if show_touches:
            cmd.append('--show-touches')
            
        if window_borderless:
            cmd.append('--window-borderless')
            
        if mouse_mode != 'sdk':
            cmd.extend(['--mouse', mouse_mode])
            
        if angle != 0:
            cmd.extend(['--angle', str(angle)])
            
        if audio_buffer != 50:
            cmd.extend(['--audio-buffer', str(audio_buffer)])
            
        if audio_source != 'output':
            cmd.extend(['--audio-source', audio_source])
            
        if video_source == 'camera':
            cmd.extend(['--video-source', 'camera'])
            if camera_id: cmd.extend(['--camera-id', camera_id])
            if camera_facing and camera_facing != 'any': cmd.extend(['--camera-facing', camera_facing])
            if camera_ar: cmd.extend(['--camera-ar', camera_ar])
            if camera_fps > 0: cmd.extend(['--camera-fps', str(camera_fps)])
            if camera_size: cmd.extend(['--camera-size', camera_size])
            
        if keyboard_mode != 'sdk':
            cmd.extend(['--keyboard', keyboard_mode])
            
        if no_control:
            cmd.append('--no-control')
            
        if no_clipboard_autosync:
            cmd.append('--no-clipboard-autosync')
            
        if no_key_repeat:
            cmd.append('--no-key-repeat')
            
        if no_mouse_hover:
            cmd.append('--no-mouse-hover')
            
        if no_power_on:
            cmd.append('--no-power-on')
            
        if otg:
            cmd.append('--otg')
            
        if print_fps:
            cmd.append('--print-fps')
            
        if record_path:
            cmd.extend(['--record', record_path])
            
        print(f"Starting mirroring: {' '.join(cmd)}")
        
        try:
            # Capture stdout and stderr to display in the UI
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
                text=True,
                bufsize=1
            )
            
            self.active_sessions[device_id] = process
            return process
            
        except Exception as e:
            raise RuntimeError(f"Failed to start scrcpy: {e}")
    
    def stop_mirroring(self, device_id: str) -> None:
        """Stop screen mirroring for a device.
        
        Args:
            device_id: Device ID
        """
        if device_id not in self.active_sessions:
            return
        
        process = self.active_sessions[device_id]
        
        try:
            # Terminate gracefully
            process.terminate()
            
            # Wait a bit for graceful shutdown
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate
                process.kill()
                process.wait()
            
        finally:
            del self.active_sessions[device_id]
    
    def is_mirroring(self, device_id: str) -> bool:
        """Check if screen mirroring is active for a device.
        
        Args:
            device_id: Device ID
            
        Returns:
            True if mirroring is active
        """
        if device_id not in self.active_sessions:
            return False
        
        process = self.active_sessions[device_id]
        
        # Check if process is still running
        if process.poll() is not None:
            # Process has terminated
            del self.active_sessions[device_id]
            return False
        
        return True
    
    def stop_all(self) -> None:
        """Stop all active mirroring sessions."""
        device_ids = list(self.active_sessions.keys())
        
        for device_id in device_ids:
            self.stop_mirroring(device_id)
    
    def _run_list_command(self, device_id: str, flag: str) -> str:
        """Run a scrcpy list command for a device."""
        cmd = [self.scrcpy_path, '-s', device_id, flag]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Error running scrcpy {flag}: {e}"

    def list_encoders(self, device_id: str) -> str:
        return self._run_list_command(device_id, '--list-encoders')

    def list_cameras(self, device_id: str) -> str:
        return self._run_list_command(device_id, '--list-cameras')

    def list_camera_sizes(self, device_id: str) -> str:
        return self._run_list_command(device_id, '--list-camera-sizes')

    def list_displays(self, device_id: str) -> str:
        return self._run_list_command(device_id, '--list-displays')

    def __del__(self):
        """Cleanup all sessions on deletion."""
        self.stop_all()
