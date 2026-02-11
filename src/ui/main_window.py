"""Main window for the droidmgr GUI."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional
from pathlib import Path
import threading

from core import DeviceManager
from .about_dialog import AboutDialog
from .preferences_dialog import PreferencesDialog
from .file_manager import FileManager
from .app_info_dialog import AppInfoDialog
from .scrcpy_settings_dialog import ScrcpySettingsDialog
from .scrcpy_output_dialog import ScrcpyOutputDialog
from .device_details_dialog import DeviceDetailsDialog


class MainWindow:
    
    def __init__(self, adb_path=None, scrcpy_path=None):
        self.root = tk.Tk()
        self.root.title("droidmgr - Android Device Manager")
        self.root.geometry("900x650")
        self.root.minsize(400, 300)  # Set minimum window size
        
        self.adb_path = adb_path
        self.scrcpy_path = scrcpy_path
        
        try:
            self.device_manager = DeviceManager(adb_path, scrcpy_path)
        except Exception as e:
            messagebox.showerror("Initialization Error", 
                               f"Failed to initialize device manager:\n{e}\n\nPlease ensure scrcpy and adb are installed.")
            self.root.destroy()
            return
        
        self.selected_device: Optional[str] = None
        self.has_devices = False
        
        # Mirroring settings
        from core import ConfigManager
        self.config = ConfigManager()
        self._load_scrcpy_settings()
        
        self._create_ui()
        self._refresh_devices()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _create_ui(self):
        self._create_menu()
        self._create_notebook()
        self._create_statusbar()
    
    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Preferences", command=self._show_preferences)
        file_menu.add_separator()
        file_menu.add_command(label="Refresh Devices", command=self._refresh_devices)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_closing)
        
        device_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Device", menu=device_menu)
        device_menu.add_command(label="Toggle Mirroring", command=self._toggle_mirroring)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)
    
    def _create_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.devices_tab = self._create_devices_tab()
        self.processes_tab = self._create_processes_tab()
        self.apps_tab = self._create_apps_tab()
        
        # Initialize File Manager
        self.files_tab = ttk.Frame(self.notebook)
        self.file_manager = FileManager(
            self.files_tab, 
            self.device_manager,
            self._set_status,
            self._show_error,
            self._require_device
        )
        
        self.notebook.add(self.devices_tab, text="Devices")
    
    def _create_statusbar(self):
        self.statusbar = ttk.Label(
            self.root,
            text="Ready",
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _create_devices_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Connected Devices")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        columns = ('ID', 'Model', 'Status', 'Mirroring')
        self.device_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.device_tree.heading('#0', text='#')
        for col in columns:
            self.device_tree.heading(col, text=col)
            self.device_tree.column(col, width=200)
        self.device_tree.column('#0', width=50)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_tree.bind('<<TreeviewSelect>>', self._on_device_select)
        self.device_tree.bind('<Double-1>', self._on_device_double_click)
        
        self.no_devices_frame = ttk.Frame(list_frame)
        
        title_label = tk.Label(self.no_devices_frame, text="No Devices Connected", 
                              font=('Arial', 16, 'bold'))
        title_label.pack(pady=(60, 20))
        
        instructions = [
            "To connect an Android device:",
            "1. Enable Developer Options on your device",
            "   (Settings → About Phone → Tap 'Build Number' 7 times)",
            "2. Enable USB Debugging",
            "   (Settings → Developer Options → USB Debugging)",
            "3. Connect your device via USB cable",
            "4. Accept the 'Allow USB Debugging' prompt on your device",
            "",
            "Your device will appear here once connected."
        ]
        
        for instruction in instructions:
            label = tk.Label(self.no_devices_frame, text=instruction, 
                           font=('Arial', 10), anchor=tk.W, justify=tk.LEFT)
            pady = 8 if instruction == "" else 2
            label.pack(anchor=tk.W, padx=100, pady=pady)
        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_devices_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_devices)
        self.refresh_devices_btn.pack(side=tk.LEFT, padx=2)
        
        self.mirror_btn = ttk.Button(btn_frame, text="Start Mirroring", command=self._toggle_mirroring)
        self.mirror_btn.pack(side=tk.LEFT, padx=2)
        
        self.scrcpy_settings_btn = ttk.Button(btn_frame, text="scrcpy Settings", command=self._show_scrcpy_settings)
        self.scrcpy_settings_btn.pack(side=tk.LEFT, padx=2)
        
        return tab
    
    def _create_processes_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Running Processes")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.system_info_label = tk.Label(list_frame, text="", anchor=tk.W, font=('Monospace', 9))
        self.system_info_label.pack(fill=tk.X, padx=5, pady=2)
        
        columns = ('PID', 'User', 'CPU%', 'Memory', 'Name')
        self.process_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.process_tree.heading('#0', text='#')
        self.process_tree.heading('PID', text='PID')
        self.process_tree.heading('User', text='User')
        self.process_tree.heading('CPU%', text='CPU%')
        self.process_tree.heading('Memory', text='Memory')
        self.process_tree.heading('Name', text='Process Name')
        
        self.process_tree.column('#0', width=40)
        self.process_tree.column('PID', width=80)
        self.process_tree.column('User', width=120)
        self.process_tree.column('CPU%', width=80)
        self.process_tree.column('Memory', width=100)
        self.process_tree.column('Name', width=350)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        self.process_tree.configure(yscrollcommand=scrollbar.set)
        self.process_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_processes_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_processes)
        self.refresh_processes_btn.pack(side=tk.LEFT, padx=2)
        
        self.kill_process_btn = ttk.Button(btn_frame, text="Kill Process", command=self._kill_process)
        self.kill_process_btn.pack(side=tk.LEFT, padx=2)
        
        return tab
    
    def _create_apps_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Installed Applications")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.app_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.app_listbox.yview)
        self.app_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app_listbox.bind('<<ListboxSelect>>', self._on_app_select)
        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_apps_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_apps)
        self.refresh_apps_btn.pack(side=tk.LEFT, padx=2)
        
        self.install_apk_btn = ttk.Button(btn_frame, text="Install APK", command=self._install_apk)
        self.install_apk_btn.pack(side=tk.LEFT, padx=2)
        
        self.start_app_btn = ttk.Button(btn_frame, text="Start App", command=self._start_app)
        self.start_app_btn.pack(side=tk.LEFT, padx=2)
        
        self.stop_app_btn = ttk.Button(btn_frame, text="Stop App", command=self._stop_app)
        self.stop_app_btn.pack(side=tk.LEFT, padx=2)
        
        return tab
    
    def _update_tab_visibility(self):
        if self.has_devices:
            self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.no_devices_frame.pack_forget()
            self._update_button_states()
            
            if self.selected_device and self.notebook.index('end') == 1:
                self.notebook.add(self.processes_tab, text="Processes")
                self.notebook.add(self.apps_tab, text="Applications")
                self.notebook.add(self.files_tab, text="Files")
            elif not self.selected_device:
                while self.notebook.index('end') > 1:
                    self.notebook.forget(1)
        else:
            self.device_tree.pack_forget()
            self.no_devices_frame.pack(fill=tk.BOTH, expand=True)
            self._update_button_states()
            
            while self.notebook.index('end') > 1:
                self.notebook.forget(1)
    
    def _update_button_states(self):
        has_selection = self.selected_device is not None
        state = tk.NORMAL if has_selection else tk.DISABLED
        
        self.mirror_btn.config(state=state)
        
        if has_selection:
            is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
            self.mirror_btn.config(text="Stop Mirroring" if is_mirroring else "Start Mirroring")
        
        self.refresh_processes_btn.config(state=state)
        self.kill_process_btn.config(state=state)
        self.refresh_apps_btn.config(state=state)
        self.install_apk_btn.config(state=state)
        
        # App specific buttons depend on both device AND app selection
        self._update_app_button_states()
    
    def _update_app_button_states(self):
        has_device = self.selected_device is not None
        has_app_selection = bool(self.app_listbox.curselection())
        
        device_state = tk.NORMAL if has_device else tk.DISABLED
        app_state = tk.NORMAL if (has_device and has_app_selection) else tk.DISABLED
        
        self.start_app_btn.config(state=app_state)
        self.stop_app_btn.config(state=app_state)
        
        self.file_manager.update_button_states(device_state)
        self.scrcpy_settings_btn.config(state=device_state)
    
    def _set_status(self, message):
        self.statusbar.config(text=message)
    
    def _show_error(self, title, message):
        messagebox.showerror(title, message)
        self._set_status(f"Error: {title}")
    
    def _show_warning(self, message):
        messagebox.showwarning("Warning", message)
        self._set_status(f"Warning: {message}")
    
    def _show_info(self, message):
        messagebox.showinfo("Success", message)
        self._set_status(message)
    
    def _show_about(self):
        AboutDialog(self.root).show()
    
    def _show_preferences(self):
        PreferencesDialog(self.root, self._on_preferences_changed).show()
        
    def _show_scrcpy_settings(self):
        if not self._require_device():
            return
            
        dialog = ScrcpySettingsDialog(self.root, self.selected_device, self.device_manager.scrcpy)
        self.root.wait_window(dialog)
        if dialog.result:
            self._load_scrcpy_settings()
            self._set_status("scrcpy settings updated")
            
    def _load_scrcpy_settings(self):
        self.mirror_settings = {
            'video_bit_rate': self.config.get('scrcpy', 'video_bit_rate', '8M'),
            'audio_bit_rate': self.config.get('scrcpy', 'audio_bit_rate', '128K'),
            'max_size': self.config.get('scrcpy', 'max_size', None),
            'max_fps': self.config.get('scrcpy', 'max_fps', 0),
            'orientation': self.config.get('scrcpy', 'orientation', '0'),
            'window_title': self.config.get('scrcpy', 'window_title', 'Droidmgr Mirroring'),
            'video_codec': self.config.get('scrcpy', 'video_codec', 'h264'),
            'audio_codec': self.config.get('scrcpy', 'audio_codec', 'opus'),
            'audio_source': self.config.get('scrcpy', 'audio_source', 'output'),
            'audio_buffer': self.config.get('scrcpy', 'audio_buffer', 50),
            'angle': self.config.get('scrcpy', 'angle', 0),
            'mouse_mode': self.config.get('scrcpy', 'mouse_mode', 'sdk'),
            'fullscreen': self.config.get('scrcpy', 'fullscreen', False),
            'always_on_top': self.config.get('scrcpy', 'always_on_top', False),
            'stay_awake': self.config.get('scrcpy', 'stay_awake', False),
            'turn_screen_off': self.config.get('scrcpy', 'turn_screen_off', False),
            'no_audio': self.config.get('scrcpy', 'no_audio', False),
            'no_video': self.config.get('scrcpy', 'no_video', False),
            'show_touches': self.config.get('scrcpy', 'show_touches', False),
            'window_borderless': self.config.get('scrcpy', 'window_borderless', False),
            'power_off_on_close': self.config.get('scrcpy', 'power_off_on_close', False),
            
            # New settings
            'video_source': self.config.get('scrcpy', 'video_source', 'display'),
            'camera_id': self.config.get('scrcpy', 'camera_id', ''),
            'camera_facing': self.config.get('scrcpy', 'camera_facing', 'any'),
            'camera_ar': self.config.get('scrcpy', 'camera_ar', ''),
            'camera_fps': self.config.get('scrcpy', 'camera_fps', 0),
            'camera_size': self.config.get('scrcpy', 'camera_size', ''),
            'keyboard_mode': self.config.get('scrcpy', 'keyboard_mode', 'sdk'),
            'no_control': self.config.get('scrcpy', 'no_control', False),
            'no_clipboard_autosync': self.config.get('scrcpy', 'no_clipboard_autosync', False),
            'no_key_repeat': self.config.get('scrcpy', 'no_key_repeat', False),
            'no_mouse_hover': self.config.get('scrcpy', 'no_mouse_hover', False),
            'no_power_on': self.config.get('scrcpy', 'no_power_on', False),
            'otg': self.config.get('scrcpy', 'otg', False),
            'print_fps': self.config.get('scrcpy', 'print_fps', False),
            'record_path': self.config.get('scrcpy', 'record_path', '') if self.config.get('scrcpy', 'record', False) else None
        }
    
    def _on_preferences_changed(self):
        from core import ConfigManager
        config = ConfigManager()
        
        adb_path = config.get('paths', 'adb')
        scrcpy_path = config.get('paths', 'scrcpy')
        
        if adb_path:
            self.adb_path = Path(adb_path)
        if scrcpy_path:
            self.scrcpy_path = Path(scrcpy_path)
            
        try:
            self.device_manager = DeviceManager(self.adb_path, self.scrcpy_path)
            self.file_manager.device_manager = self.device_manager
            self._set_status("Preferences updated")
            self._refresh_devices()
            
            if self.selected_device:
                self.file_manager.refresh()
        except Exception as e:
            self._show_error("Error", f"Failed to reinitialize with new settings:\n{e}")
    
    def _require_device(self):
        if not self.selected_device:
            self._show_warning("Please select a device first")
            return False
        return True
    
    def _on_device_select(self, event):
        selection = self.device_tree.selection()
        if selection:
            item = self.device_tree.item(selection[0])
            values = item['values']
            if values:
                self.selected_device = values[0]
                self._set_status(f"Selected device: {self.selected_device}")
                self._update_tab_visibility()
                self._refresh_processes()
                self._refresh_apps()
                self.file_manager.set_device(self.selected_device)

    def _on_device_double_click(self, event):
        if self.selected_device:
            DeviceDetailsDialog(self.root, self.selected_device, self.device_manager)
    
    def _refresh_devices(self):
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        
        try:
            devices = self.device_manager.get_devices()
            self.has_devices = len(devices) > 0
            self._update_tab_visibility()
            
            for idx, device in enumerate(devices, 1):
                mirroring = "Yes" if device.get('is_mirroring', False) else "No"
                self.device_tree.insert('', tk.END, text=str(idx),
                                       values=(device['id'], device.get('model', 'Unknown'),
                                              device['status'], mirroring))
            self._set_status(f"Found {len(devices)} device(s)")
        except Exception as e:
            self.has_devices = False
            self._update_tab_visibility()
            self._show_error("Device Refresh Error", str(e))
        
        self.root.after(5000, self._refresh_devices)
    
    def _toggle_mirroring(self):
        if not self._require_device():
            return
        
        is_mirroring = self.device_manager.scrcpy.is_mirroring(self.selected_device)
        
        if is_mirroring:
            try:
                self.device_manager.stop_mirroring(self.selected_device)
                self.mirror_btn.config(text="Start Mirroring")
                self._set_status("Mirroring stopped")
            except Exception as e:
                self._show_error("Mirroring Error", str(e))
        else:
            def task():
                try:
                    process = self.device_manager.start_mirroring(self.selected_device, **self.mirror_settings)
                    
                    def start_dialog():
                        self.mirror_btn.config(text="Stop Mirroring")
                        self._set_status("Mirroring started")
                        ScrcpyOutputDialog(self.root, process, self.selected_device, self.device_manager.stop_mirroring)
                        
                    self.root.after(0, start_dialog)
                except Exception as e:
                    msg = str(e)
                    self.root.after(0, lambda: self._show_error("Mirroring Error", msg))
            
            self._set_status("Starting screen mirroring...")
            threading.Thread(target=task, daemon=True).start()
    
    def _refresh_processes(self):
        if not self.selected_device:
            return
        
        for item in self.process_tree.get_children():
            self.process_tree.delete(item)
        
        def task():
            try:
                processes = self.device_manager.get_processes(self.selected_device)
                stats = self.device_manager.adb.get_system_stats(self.selected_device)
                
                def update():
                    system_info = f"System: {stats.get('cpu_cores', '?')} cores | "
                    system_info += f"Memory: {stats.get('free_memory', '?')} free / {stats.get('total_memory', '?')} total"
                    self.system_info_label.config(text=system_info)
                    
                    for idx, proc in enumerate(processes, 1):
                        cpu_color = ''
                        try:
                            cpu_val = float(proc.get('cpu', 0))
                            if cpu_val > 50:
                                cpu_color = 'red'
                            elif cpu_val > 20:
                                cpu_color = 'orange'
                        except:
                            pass
                        
                        item_id = self.process_tree.insert(
                            '', tk.END, text=str(idx),
                            values=(proc['pid'], proc['user'], proc.get('cpu', '0'), 
                                   proc.get('mem', '0 MB'), proc['name'])
                        )
                        
                        if cpu_color:
                            self.process_tree.item(item_id, tags=(cpu_color,))
                    
                    self.process_tree.tag_configure('red', foreground='red')
                    self.process_tree.tag_configure('orange', foreground='orange')
                    
                    self._set_status(f"Found {len(processes)} processes")
                self.root.after(0, update)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Process Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()
    
    def _kill_process(self):
        if not self._require_device():
            return
        
        selection = self.process_tree.selection()
        if not selection:
            self._show_warning("Please select a process to kill")
            return
        
        pid = self.process_tree.item(selection[0])['values'][0]
        if messagebox.askyesno("Confirm", f"Kill process {pid}?"):
            try:
                self.device_manager.kill_process(self.selected_device, pid)
                self._refresh_processes()
                self._set_status(f"Killed process {pid}")
            except Exception as e:
                self._show_error("Kill Process Error", str(e))
    
    def _refresh_apps(self):
        if not self.selected_device:
            return
        
        self.app_listbox.delete(0, tk.END)
        
        def task():
            try:
                apps = self.device_manager.get_apps(self.selected_device)
                def update():
                    for app in apps:
                        self.app_listbox.insert(tk.END, app)
                    self._update_app_button_states()
                    self._set_status(f"Found {len(apps)} applications")
                self.root.after(0, update)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("App Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()
    
    def _on_app_select(self, event):
        self._update_app_button_states()
        
        selection = self.app_listbox.curselection()
        if not selection:
            return
            
        package = self.app_listbox.get(selection[0])
        
        def task():
            try:
                info = self.device_manager.adb.get_app_info(self.selected_device, package)
                self.root.after(0, lambda: AppInfoDialog(self.root, info))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("App Info Error", msg))
                
        threading.Thread(target=task, daemon=True).start()
    
    def _start_app(self):
        if not self._require_device():
            return
        
        selection = self.app_listbox.curselection()
        if not selection:
            self._show_warning("Please select an app to start")
            return
        
        package = self.app_listbox.get(selection[0])
        
        def task():
            try:
                self.device_manager.start_app(self.selected_device, package)
                self.root.after(0, lambda: self._show_info(f"Started {package}"))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Start App Error", msg))
        
        self._set_status(f"Starting {package}...")
        threading.Thread(target=task, daemon=True).start()
    
    def _stop_app(self):
        if not self._require_device():
            return
        
        selection = self.app_listbox.curselection()
        if not selection:
            self._show_warning("Please select an app to stop")
            return
        
        package = self.app_listbox.get(selection[0])
        try:
            self.device_manager.stop_app(self.selected_device, package)
            self._show_info(f"Stopped {package}")
        except Exception as e:
            self._show_error("Stop App Error", str(e))
    
    def _install_apk(self):
        if not self._require_device():
            return
        
        apk_path = filedialog.askopenfilename(
            title="Select APK file",
            filetypes=[("APK files", "*.apk"), ("All files", "*.*")]
        )
        
        if not apk_path:
            return
        
        def task():
            try:
                self.device_manager.adb.install_apk(self.selected_device, apk_path)
                self.root.after(0, lambda: self._show_info(f"APK installed successfully"))
                self.root.after(0, lambda: self._refresh_apps())
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Install APK Error", msg))
        
        self._set_status(f"Installing APK...")
        threading.Thread(target=task, daemon=True).start()
    
    
    def _on_closing(self):
        self.device_manager.cleanup()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()
