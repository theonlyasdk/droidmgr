import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
from core import ConfigManager

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                      background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"), padx=5, pady=2)
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

class ScrcpySettingsDialog(tk.Toplevel):
    def __init__(self, parent, device_id=None, scrcpy_manager=None):
        super().__init__(parent)
        self.title("scrcpy Settings")
        self.parent = parent
        self.device_id = device_id
        self.scrcpy_manager = scrcpy_manager
        self.config = ConfigManager()
        self.result = None
        
        self.geometry("600x550")
        self.resizable(True, True)
        self.transient(parent)
        
        # Main container
        self.container = ttk.Frame(self, padding="10")
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # Tabs for better organization
        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.video_tab = ttk.Frame(self.notebook, padding=10)
        self.audio_tab = ttk.Frame(self.notebook, padding=10)
        self.control_tab = ttk.Frame(self.notebook, padding=10)
        self.window_tab = ttk.Frame(self.notebook, padding=10)
        
        self.notebook.add(self.video_tab, text="Video/Camera")
        self.notebook.add(self.audio_tab, text="Audio")
        self.notebook.add(self.control_tab, text="Control")
        self.notebook.add(self.window_tab, text="Window/Other")
        
        self._create_video_settings()
        self._create_audio_settings()
        self._create_control_settings()
        self._create_window_settings()
        
        # Buttons
        btn_frame = ttk.Frame(self.container, padding=(0, 10, 0, 0))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        
        # Initial states
        self._toggle_camera_settings()
        self._toggle_record_settings()
        
        # Ensure window is visible before grabbing
        self.wait_visibility()
        self.grab_set()

    def _add_tooltip(self, widget, text):
        ToolTip(widget, text)

    def _create_video_settings(self):
        self.video_tab.columnconfigure(1, weight=1)
        row = 0
        # Video Source
        ttk.Label(self.video_tab, text="Video Source:").grid(row=row, column=0, sticky='w', pady=5)
        self.video_source_var = tk.StringVar(value=self.config.get('scrcpy', 'video_source', 'display'))
        self.video_source_cb = ttk.Combobox(self.video_tab, textvariable=self.video_source_var, values=['display', 'camera'], state='readonly')
        self.video_source_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self.video_source_cb.bind("<<ComboboxSelected>>", lambda e: self._toggle_camera_settings())
        self._add_tooltip(self.video_source_cb, "Select whether to mirror the display or a device camera.")
        row += 1

        # Camera settings
        self.camera_frame = ttk.LabelFrame(self.video_tab, text="Camera Settings", padding=10)
        self.camera_frame.grid(row=row, column=0, columnspan=2, sticky='new', pady=10)
        self.camera_frame.columnconfigure(1, weight=1)
        
        c_row = 0
        ttk.Label(self.camera_frame, text="Camera ID:").grid(row=c_row, column=0, sticky='w', pady=2)
        
        id_frame = ttk.Frame(self.camera_frame)
        id_frame.grid(row=c_row, column=1, sticky='ew', pady=2, padx=5)
        id_frame.columnconfigure(0, weight=1)
        
        self.camera_id_var = tk.StringVar(value=self.config.get('scrcpy', 'camera_id', ''))
        self.camera_id_ent = ttk.Entry(id_frame, textvariable=self.camera_id_var)
        self.camera_id_ent.grid(row=0, column=0, sticky='ew')
        
        self.choose_cam_btn = ttk.Button(id_frame, text="Choose...", width=10, command=self._choose_camera)
        self.choose_cam_btn.grid(row=0, column=1, padx=(5, 0))
        
        self._add_tooltip(self.camera_id_ent, "Specific camera ID to mirror. Click 'Choose' to list available cameras.")
        c_row += 1

        ttk.Label(self.camera_frame, text="Facing:").grid(row=c_row, column=0, sticky='w', pady=2)
        self.camera_facing_var = tk.StringVar(value=self.config.get('scrcpy', 'camera_facing', 'any'))
        self.camera_facing_cb = ttk.Combobox(self.camera_frame, textvariable=self.camera_facing_var, values=['any', 'front', 'back', 'external'], state='readonly')
        self.camera_facing_cb.grid(row=c_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.camera_facing_cb, "Select which camera facing to use (front, back, or external).")
        c_row += 1

        ttk.Label(self.camera_frame, text="Aspect Ratio:").grid(row=c_row, column=0, sticky='w', pady=2)
        self.camera_ar_var = tk.StringVar(value=self.config.get('scrcpy', 'camera_ar', ''))
        self.camera_ar_ent = ttk.Entry(self.camera_frame, textvariable=self.camera_ar_var)
        self.camera_ar_ent.grid(row=c_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.camera_ar_ent, "Camera aspect ratio (e.g., '4:3', '1.6', or 'sensor').")
        c_row += 1

        ttk.Label(self.camera_frame, text="Camera FPS:").grid(row=c_row, column=0, sticky='w', pady=2)
        self.camera_fps_var = tk.StringVar(value=str(self.config.get('scrcpy', 'camera_fps', 0)))
        self.camera_fps_spin = ttk.Spinbox(self.camera_frame, from_=0, to=120, textvariable=self.camera_fps_var)
        self.camera_fps_spin.grid(row=c_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.camera_fps_spin, "Target frame rate for the camera mirroring.")
        c_row += 1

        ttk.Label(self.camera_frame, text="Camera Size:").grid(row=c_row, column=0, sticky='w', pady=2)
        self.camera_size_var = tk.StringVar(value=self.config.get('scrcpy', 'camera_size', ''))
        self.camera_size_ent = ttk.Entry(self.camera_frame, textvariable=self.camera_size_var)
        self.camera_size_ent.grid(row=c_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.camera_size_ent, "Explicit camera size (e.g. 1920x1080).")
        
        row += 1

        # General Video settings
        self.gen_video_frame = ttk.LabelFrame(self.video_tab, text="General Video", padding=10)
        self.gen_video_frame.grid(row=row, column=0, columnspan=2, sticky='new', pady=5)
        self.gen_video_frame.columnconfigure(1, weight=1)
        
        gv_row = 0
        ttk.Label(self.gen_video_frame, text="Bitrate:").grid(row=gv_row, column=0, sticky='w', pady=2)
        self.video_bitrate_var = tk.StringVar(value=self.config.get('scrcpy', 'video_bit_rate', '8M'))
        self.video_bitrate_cb = ttk.Combobox(self.gen_video_frame, textvariable=self.video_bitrate_var, values=['2M', '4M', '8M', '16M', '32M'])
        self.video_bitrate_cb.grid(row=gv_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.video_bitrate_cb, "Set the video bit rate (e.g. 8M).")
        gv_row += 1

        ttk.Label(self.gen_video_frame, text="Codec:").grid(row=gv_row, column=0, sticky='w', pady=2)
        self.video_codec_var = tk.StringVar(value=self.config.get('scrcpy', 'video_codec', 'h264'))
        self.video_codec_cb = ttk.Combobox(self.gen_video_frame, textvariable=self.video_codec_var, values=['h264', 'h265', 'av1'], state='readonly')
        self.video_codec_cb.grid(row=gv_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.video_codec_cb, "Select video codec (H264, H265, or AV1).")
        gv_row += 1

        ttk.Label(self.gen_video_frame, text="Max Size:").grid(row=gv_row, column=0, sticky='w', pady=2)
        max_size = self.config.get('scrcpy', 'max_size', 0)
        self.max_size_var = tk.StringVar(value=str(max_size if max_size else 0))
        self.max_size_cb = ttk.Combobox(self.gen_video_frame, textvariable=self.max_size_var, values=['0', '720', '1080', '1440', '1920'])
        self.max_size_cb.grid(row=gv_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.max_size_cb, "Limit both width and height to value (0 for no limit).")
        gv_row += 1

        ttk.Label(self.gen_video_frame, text="Max FPS:").grid(row=gv_row, column=0, sticky='w', pady=2)
        self.max_fps_var = tk.StringVar(value=str(self.config.get('scrcpy', 'max_fps', 0)))
        self.max_fps_cb = ttk.Combobox(self.gen_video_frame, textvariable=self.max_fps_var, values=['0', '30', '60', '90', '120'])
        self.max_fps_cb.grid(row=gv_row, column=1, sticky='ew', pady=2, padx=5)
        self._add_tooltip(self.max_fps_cb, "Limit mirroring frame rate (0 for no limit).")
        gv_row += 1
        
        self.no_video_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_video', False))
        chk = ttk.Checkbutton(self.gen_video_frame, text="Disable Video forwarding (--no-video)", variable=self.no_video_var)
        chk.grid(row=gv_row, column=0, columnspan=2, sticky='w', pady=5)
        self._add_tooltip(chk, "Mirror without video (audio only).")

    def _toggle_camera_settings(self):
        show = self.video_source_var.get() == 'camera'
        if show:
            self.camera_frame.grid()
        else:
            self.camera_frame.grid_remove()

    def _choose_camera(self):
        if not self.device_id or not self.scrcpy_manager:
            messagebox.showwarning("Warning", "No device selected or scrcpy manager not available.")
            return
            
        try:
            output = self.scrcpy_manager.list_cameras(self.device_id)
            # Match formats like: --camera-id=0  (back, 4096x3072...)
            # or the older id="0" format if it still exists
            matches = re.findall(r'--camera-id=(\S+)\s+(.*)', output)
            if not matches:
                ids = re.findall(r'id="([^"]+)"', output)
                matches = [(cid, "") for cid in ids]
            
            if not matches:
                messagebox.showinfo("Cameras", "No cameras found or failed to list cameras.\n\nOutput:\n" + output)
                return
                
            # Create a simple selection dialog
            top = tk.Toplevel(self)
            top.title("Select Camera")
            top.geometry("450x400")
            top.transient(self)
            top.grab_set()
            
            main = ttk.Frame(top, padding=10)
            main.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(main, text="Available Cameras:", font=('Arial', 10, 'bold')).pack(pady=(0, 10))
            
            lb = tk.Listbox(main, font=('Courier New', 9))
            lb.pack(fill=tk.BOTH, expand=True)
            
            for cid, desc in matches:
                lb.insert(tk.END, f"{cid.ljust(5)} {desc}")
                
            def on_select():
                selection = lb.curselection()
                if selection:
                    # Extract the ID (first word)
                    full_text = lb.get(selection[0])
                    cid = full_text.split()[0]
                    self.camera_id_var.set(cid)
                    top.destroy()
                    
            ttk.Button(main, text="Select", command=on_select).pack(pady=10)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list cameras: {e}")

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

    def _create_control_settings(self):
        self.control_tab.columnconfigure(1, weight=1)
        row = 0
        # Mouse Mode
        ttk.Label(self.control_tab, text="Mouse Mode:").grid(row=row, column=0, sticky='w', pady=5)
        self.mouse_mode_var = tk.StringVar(value=self.config.get('scrcpy', 'mouse_mode', 'sdk'))
        self.mouse_mode_cb = ttk.Combobox(self.control_tab, textvariable=self.mouse_mode_var, values=['sdk', 'uhid', 'aoa', 'disabled'], state='readonly')
        self.mouse_mode_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.mouse_mode_cb, "Select mouse input method. 'uhid' and 'aoa' simulate a physical mouse.")
        row += 1

        # Keyboard Mode
        ttk.Label(self.control_tab, text="Keyboard Mode:").grid(row=row, column=0, sticky='w', pady=5)
        self.keyboard_mode_var = tk.StringVar(value=self.config.get('scrcpy', 'keyboard_mode', 'sdk'))
        self.keyboard_mode_cb = ttk.Combobox(self.control_tab, textvariable=self.keyboard_mode_var, values=['sdk', 'uhid', 'aoa', 'disabled'], state='readonly')
        self.keyboard_mode_cb.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(self.keyboard_mode_cb, "Select keyboard input method. 'uhid' and 'aoa' simulate a physical keyboard.")
        row += 1

        # Checkboxes
        check_frame = ttk.Frame(self.control_tab)
        check_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        
        self.no_control_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_control', False))
        c1 = ttk.Checkbutton(check_frame, text="Read-only mode (No control)", variable=self.no_control_var)
        c1.pack(anchor='w', pady=2)
        self._add_tooltip(c1, "Disable device control (mirror only).")
        
        self.no_clipboard_autosync_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_clipboard_autosync', False))
        c2 = ttk.Checkbutton(check_frame, text="Disable Clipboard Autosync", variable=self.no_clipboard_autosync_var)
        c2.pack(anchor='w', pady=2)
        self._add_tooltip(c2, "Disable automatic clipboard synchronization between computer and device.")
        
        self.no_key_repeat_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_key_repeat', False))
        c3 = ttk.Checkbutton(check_frame, text="Disable Key Repeat", variable=self.no_key_repeat_var)
        c3.pack(anchor='w', pady=2)
        self._add_tooltip(c3, "Do not forward repeated key events when a key is held down.")
        
        self.no_mouse_hover_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_mouse_hover', False))
        c4 = ttk.Checkbutton(check_frame, text="Disable Mouse Hover", variable=self.no_mouse_hover_var)
        c4.pack(anchor='w', pady=2)
        self._add_tooltip(c4, "Do not forward mouse hover (motion without clicks) events.")
        
        self.no_power_on_var = tk.BooleanVar(value=self.config.get('scrcpy', 'no_power_on', False))
        c5 = ttk.Checkbutton(check_frame, text="Do Not Power On on Start", variable=self.no_power_on_var)
        c5.pack(anchor='w', pady=2)
        self._add_tooltip(c5, "Do not power on the device screen when scrcpy starts.")
        
        self.otg_var = tk.BooleanVar(value=self.config.get('scrcpy', 'otg', False))
        c6 = ttk.Checkbutton(check_frame, text="OTG Mode", variable=self.otg_var)
        c6.pack(anchor='w', pady=2)
        self._add_tooltip(c6, "Simulate physical HID devices. Requires USB and often no ADB.")

    def _create_window_settings(self):
        self.window_tab.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(self.window_tab, text="Window Title:").grid(row=row, column=0, sticky='w', pady=5)
        self.window_title_var = tk.StringVar(value=self.config.get('scrcpy', 'window_title', 'Droidmgr Mirroring'))
        title_ent = ttk.Entry(self.window_tab, textvariable=self.window_title_var)
        title_ent.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(title_ent, "Custom title for the mirroring window.")
        row += 1
        
        # Angle
        ttk.Label(self.window_tab, text="Angle (0-360):").grid(row=row, column=0, sticky='w', pady=5)
        self.angle_var = tk.StringVar(value=str(self.config.get('scrcpy', 'angle', 0)))
        angle_spin = ttk.Spinbox(self.window_tab, from_=0, to=360, textvariable=self.angle_var)
        angle_spin.grid(row=row, column=1, sticky='ew', pady=5, padx=5)
        self._add_tooltip(angle_spin, "Set the rotation angle in degrees.")
        row += 1

        check_frame = ttk.Frame(self.window_tab)
        check_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)

        checks = [
            ("Fullscreen", "fullscreen", "Start scrcpy in fullscreen mode."),
            ("Always on Top", "always_on_top", "Keep the scrcpy window always on top."),
            ("Borderless Window", "window_borderless", "Remove window decorations."),
            ("Stay Awake", "stay_awake", "Prevent the device from sleeping."),
            ("Turn off device screen", "turn_screen_off", "Turn off the hardware screen during mirroring."),
            ("Show physical touches", "show_touches", "Visually highlight touches on the screen."),
            ("Power off device on close", "power_off_on_close", "Power off the device when scrcpy is closed."),
            ("Print FPS in logs", "print_fps", "Log the frame rate to the console.")
        ]
        
        self.check_vars = {}
        for text, key, tooltip in checks:
            var = tk.BooleanVar(value=self.config.get('scrcpy', key, False))
            self.check_vars[key] = var
            cb = ttk.Checkbutton(check_frame, text=text, variable=var)
            cb.pack(anchor='w', pady=2)
            self._add_tooltip(cb, tooltip)

        row += 1

        # Recording
        rec_frame = ttk.LabelFrame(self.window_tab, text="Recording", padding=10)
        rec_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        rec_frame.columnconfigure(0, weight=1)
        
        self.record_var = tk.BooleanVar(value=self.config.get('scrcpy', 'record', False))
        cr = ttk.Checkbutton(rec_frame, text="Record to file", variable=self.record_var, command=self._toggle_record_settings)
        cr.grid(row=0, column=0, sticky='w')
        
        path_frame = ttk.Frame(rec_frame)
        path_frame.grid(row=1, column=0, sticky='ew', pady=5)
        path_frame.columnconfigure(0, weight=1)
        
        self.record_path_var = tk.StringVar(value=self.config.get('scrcpy', 'record_path', ''))
        self.record_path_ent = ttk.Entry(path_frame, textvariable=self.record_path_var)
        self.record_path_ent.grid(row=0, column=0, sticky='ew')
        
        # Placeholder logic
        self.placeholder = "e.g. /path/to/recording.mp4"
        self.record_path_ent.bind("<FocusIn>", self._on_path_focus_in)
        self.record_path_ent.bind("<FocusOut>", self._on_path_focus_out)
        self._on_path_focus_out(None) # Initial state

        self.record_browse_btn = ttk.Button(path_frame, text="Browse...", width=10, command=self._browse_record_path)
        self.record_browse_btn.grid(row=0, column=1, padx=(5, 0))

    def _on_path_focus_in(self, event):
        if self.record_path_var.get() == self.placeholder:
            self.record_path_var.set("")
            self.record_path_ent.config(foreground='black')

    def _on_path_focus_out(self, event):
        if not self.record_path_var.get():
            self.record_path_var.set(self.placeholder)
            self.record_path_ent.config(foreground='gray')

    def _toggle_record_settings(self):
        state = tk.NORMAL if self.record_var.get() else tk.DISABLED
        self.record_path_ent.config(state=state)
        self.record_browse_btn.config(state=state)

    def _browse_record_path(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("MKV Video", "*.mkv"), ("All Files", "*.*")]
        )
        if filename:
            self.record_path_var.set(filename)
            self.record_var.set(True)
            self.record_path_ent.config(foreground='black')

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
