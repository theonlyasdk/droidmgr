"""MainWindow mixin: Processes tab, refresh, kill, sort."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional
from .dpi import scale_size
from .process_graph import ProcessHistoryWindow
from .misc_tab import MiscTab
from .main_utils import _parse_memory, _is_offline_error
from core import ADBDeviceOfflineError, ADBDeviceNotFoundError


class _ProcessesTabMixin:
    """_ProcessesTabMixin for MainWindow (see main_window.py)."""

    def _create_processes_tab(self):
        tab = ttk.Frame(self.notebook)
        
        list_frame = ttk.LabelFrame(tab, text="Running Processes")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.system_info_label = tk.Label(list_frame, text="", anchor=tk.W, font=('Monospace', 9))
        self.system_info_label.pack(fill=tk.X, padx=5, pady=2)
        
        columns = ('PID', 'User', 'CPU%', 'Memory', 'Name')
        self.process_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings')
        
        self.process_sort_col = 'CPU%'
        self.process_sort_reverse = True
        
        self.process_tree.heading('#0', text='#')
        self.process_tree.heading('PID', text='PID', command=lambda: self._sort_processes_by_column('PID'))
        self.process_tree.heading('User', text='User', command=lambda: self._sort_processes_by_column('User'))
        self.process_tree.heading('CPU%', text='CPU%', command=lambda: self._sort_processes_by_column('CPU%'))
        self.process_tree.heading('Memory', text='Memory', command=lambda: self._sort_processes_by_column('Memory'))
        self.process_tree.heading('Name', text='Process Name', command=lambda: self._sort_processes_by_column('Name'))

        
        self.process_tree.column('#0', width=scale_size(40, self.root))
        self.process_tree.column('PID', width=scale_size(80, self.root))
        self.process_tree.column('User', width=scale_size(120, self.root))
        self.process_tree.column('CPU%', width=scale_size(80, self.root))
        self.process_tree.column('Memory', width=scale_size(100, self.root))
        self.process_tree.column('Name', width=scale_size(350, self.root))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.process_tree.yview)
        self.process_tree.configure(yscrollcommand=scrollbar.set)
        self.process_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.process_tree.bind('<Double-1>', self._show_process_info)

        
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.refresh_processes_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_processes)
        self.refresh_processes_btn.pack(side=tk.LEFT, padx=2)
        
        self.kill_process_btn = ttk.Button(btn_frame, text="Kill Process", command=self._kill_process)
        self.kill_process_btn.pack(side=tk.LEFT, padx=2)
        
        self.process_graph_btn = ttk.Button(btn_frame, text="Process History", command=self._open_process_graph)
        self.process_graph_btn.pack(side=tk.LEFT, padx=2)
        
        self.copy_processes_btn = ttk.Button(btn_frame, text="Copy Process List", command=self._copy_processes_list)
        self.copy_processes_btn.pack(side=tk.RIGHT, padx=2)
        
        return tab

    def _open_process_graph(self):
        """Open the process history window, or point the open one at this device."""
        if not self._require_device():
            return
        
        window = getattr(self, 'process_history_window', None)
        if window is not None and window.winfo_exists():
            # Only reset when the device is a different one, so that clicking
            # the button again just brings the window forward instead of
            # throwing away the history it is holding.
            if window.device_id != self.selected_device:
                window.set_device(self.selected_device)
            window.deiconify()
            window.lift()
            window.focus_force()
            return
        
        self.process_history_window = ProcessHistoryWindow(
            self.root, self.selected_device, self.device_manager)

    def _refresh_processes(self):
        if not self.selected_device:
            return
        
        # Check device readiness before querying
        try:
            if not self.device_manager.is_device_ready(self.selected_device):
                status = None
                if hasattr(self.device_manager, 'get_device_status'):
                    status = self.device_manager.get_device_status(self.selected_device)
                status_str = status.lower() if status else 'offline'
                for item in self.process_tree.get_children():
                    self.process_tree.delete(item)
                if status_str == 'unauthorized':
                    msg = "Device is unauthorized. Please accept the USB debugging prompt on your phone screen."
                else:
                    msg = "Device is offline. Reconnect USB cable or restart ADB."
                self.system_info_label.config(text=msg)
                self._set_status(f"Device '{self.selected_device}' is {status_str}.")
                return
        except Exception:
            pass

        # Save selection and scroll position
        selected_items = self.process_tree.selection()
        selected_pids = []
        for item_id in selected_items:
            values = self.process_tree.item(item_id, 'values')
            if values:
                selected_pids.append(values[0])
        
        yview = self.process_tree.yview()
        
        def task():
            try:
                import concurrent.futures
                device = self.selected_device
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    f_proc = executor.submit(self.device_manager.get_processes, device)
                    f_stats = executor.submit(self.device_manager.adb.get_system_stats, device)
                    processes = f_proc.result(timeout=15)
                    stats = f_stats.result(timeout=15)

                
                # Sort processes based on the saved column and direction
                if hasattr(self, 'process_sort_col') and self.process_sort_col:
                    col = self.process_sort_col
                    reverse = self.process_sort_reverse
                    
                    def get_proc_sort_key(proc):
                        if col == 'PID':
                            try:
                                return int(proc['pid'])
                            except ValueError:
                                return 0
                        elif col == 'CPU%':
                            try:
                                return float(proc.get('cpu', 0))
                            except ValueError:
                                return 0.0
                        elif col == 'Memory':
                            try:
                                return _parse_memory(proc.get('mem', '0 MB'))
                            except Exception:
                                return 0.0
                        elif col == 'User':
                            return proc['user'].lower()
                        else:
                            return proc['name'].lower()
                            
                    processes.sort(key=get_proc_sort_key, reverse=reverse)

                
                def update():
                    if not self.notebook.winfo_exists():
                        return
                    cur_sel = self.notebook.select()
                    if cur_sel and self.notebook.tab(cur_sel, 'text') != 'Processes':
                        return
                    # Clear existing items inside the main thread to avoid intermediate empty states
                    for item in self.process_tree.get_children():
                        self.process_tree.delete(item)
                        
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
                            
                        # Restore selection if it matches one of the saved PIDs
                        if proc['pid'] in selected_pids:
                            self.process_tree.selection_add(item_id)
                            self.process_tree.focus(item_id)
                    
                    self.process_tree.tag_configure('red', foreground='red')
                    self.process_tree.tag_configure('orange', foreground='orange')
                    
                    # Restore scroll position
                    if yview:
                        self.process_tree.yview_moveto(yview[0])
                        
                    self._set_status(f"Found {len(processes)} processes")
                self.root.after(0, update)
            except (ADBDeviceOfflineError, ADBDeviceNotFoundError):
                def handle_offline():
                    for item in self.process_tree.get_children():
                        self.process_tree.delete(item)
                    self.system_info_label.config(text="Device is offline or disconnected.")
                    self._set_status(f"Device '{device}' is offline or disconnected.")
                self.root.after(0, handle_offline)
            except concurrent.futures.TimeoutError:
                self.root.after(0, lambda: self._set_status("Process query timed out after 15 seconds."))
            except Exception as e:
                msg = str(e)
                if _is_offline_error(msg):
                    def handle_offline():
                        for item in self.process_tree.get_children():
                            self.process_tree.delete(item)
                        self.system_info_label.config(text="Device is offline or disconnected.")
                        self._set_status(f"Device '{device}' is offline or disconnected.")
                    self.root.after(0, handle_offline)
                else:
                    self.root.after(0, lambda: self._show_error("Process Refresh Error", msg))
        
        threading.Thread(target=task, daemon=True).start()

    def _kill_process(self):
        if not self._require_device():
            return
        
        selection = self.process_tree.selection()
        if not selection:
            self._show_warning("Please select a process to kill")
            return
        
        values = self.process_tree.item(selection[0])['values']
        if not values or len(values) < 5:
            return
            
        pid = str(values[0]).strip()
        user = str(values[1]).strip()
        name = str(values[4]).strip()
        
        # 1. Check for PIDs 1 or 2
        is_critical_pid = pid in ('1', '2')
        
        # 2. Check for expanded core Android processes
        CORE_PROCESSES = {
            'system_server', 'com.android.systemui', 'com.android.phone', 'init', 'adbd',
            'surfaceflinger', 'zygote', 'zygote64', 'lmkd', 'vold', 'servicemanager',
            'keystore', 'keystore2', 'hwservicemanager', 'netd', 'logd', 'tombstoned',
            'ueventd', 'healthd', 'storaged', 'auditd', 'kthreadd'
        }
        is_core_name = name in CORE_PROCESSES
        
        # 3. Check for root kernel workers
        CRITICAL_PREFIXES = ('kworker', 'ksoftirqd', 'migration', 'watchdog', 'rcu_')
        is_kernel_worker = (user == 'root' and any(name.startswith(p) for p in CRITICAL_PREFIXES))
        
        if is_critical_pid or is_core_name or is_kernel_worker:
            msg = (
                f"Warning: '{name}' (PID: {pid}) is a core Android system/kernel process.\n\n"
                "Terminating this process may cause your device to crash, reboot, or lose connectivity.\n\n"
                "Are you sure you want to proceed and force-kill this process?"
            )
            if not messagebox.askyesno("Warning - Core System Process", msg, icon=messagebox.WARNING):
                return
        else:
            # Check for system UID / system process elevated warning
            is_system_uid = False
            if user in ('root', 'system'):
                is_system_uid = True
            elif user.isdigit() and int(user) < 1000:
                is_system_uid = True
            elif name.startswith(('com.android.', 'com.google.android.')):
                is_system_uid = True
                
            if is_system_uid:
                msg = (
                    f"Process '{name}' (PID: {pid}, User: {user}) is a system service.\n\n"
                    "Terminating it may affect system functionality or cause it to automatically restart.\n\n"
                    "Do you want to terminate this process?"
                )
                if not messagebox.askyesno("Confirm Kill System Process", msg, icon=messagebox.WARNING):
                    return
            else:
                if not messagebox.askyesno("Confirm Kill", f"Kill process {pid} ({name})?"):
                    return

        device_id = self.selected_device
        def task():
            try:
                self.device_manager.kill_process(device_id, pid)
                self.root.after(0, lambda: self._set_status(f"Sent kill signal to process {pid} ({name})"))
                
                # Post-kill verification after 500ms
                import time
                time.sleep(0.5)
                
                processes = self.device_manager.get_processes(device_id)
                still_running = any(str(p.get('pid')) == pid for p in processes)
                
                def update_ui():
                    self._refresh_processes()
                    if still_running:
                        self._show_warning(f"Process {pid} ({name}) is still running.\n\nIt may require root privileges or may have automatically restarted.")
                    else:
                        self._set_status(f"Killed process {pid} ({name})")
                        
                self.root.after(0, update_ui)
                
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_error("Kill Process Error", msg))
                
        threading.Thread(target=task, daemon=True).start()

    def _sort_processes_by_column(self, col):
        if hasattr(self, 'process_sort_col') and self.process_sort_col == col:
            self.process_sort_reverse = not self.process_sort_reverse
        else:
            self.process_sort_col = col
            if col in ('PID', 'User', 'Name'):
                self.process_sort_reverse = False
            else:
                self.process_sort_reverse = True
                
        # Immediate UI sorting for instant feedback
        children = [(self.process_tree.set(k, col), k) for k in self.process_tree.get_children('')]
        
        def get_sort_key(item):
            val = item[0]
            if col == 'PID':
                try:
                    return int(val)
                except ValueError:
                    return 0
            elif col == 'CPU%':
                try:
                    return float(val.replace('%', ''))
                except ValueError:
                    return 0.0
            elif col == 'Memory':
                try:
                    return _parse_memory(val)
                except Exception:
                    return 0.0
            else:
                return val.lower()
                
        children.sort(key=get_sort_key, reverse=self.process_sort_reverse)
        
        for index, (_, k) in enumerate(children):
            self.process_tree.move(k, '', index)
            
        self._set_status(f"Sorted processes by {col} ({'descending' if self.process_sort_reverse else 'ascending'})")

