"""Video source and camera settings for the scrcpy settings dialog."""

import re
import tkinter as tk
from tkinter import messagebox, ttk
from .dpi import setup_window_dpi


class VideoSettingsMixin:
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
            top.transient(self)
            setup_window_dpi(top, base_width=450, base_height=400, parent=self)
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
