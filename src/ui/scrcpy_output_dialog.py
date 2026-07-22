import tkinter as tk
from tkinter import ttk
import threading
import queue

class ScrcpyOutputDialog(tk.Toplevel):
    def __init__(self, parent, process, device_id, stop_callback):
        super().__init__(parent)
        self.title(f"scrcpy Output - {device_id}")
        self.geometry("600x400")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.process = process
        self.device_id = device_id
        self.stop_callback = stop_callback
        self.is_running = True
        self.queue = queue.Queue()
        
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Log text area
        self.log_text = tk.Text(frame, wrap=tk.WORD, height=15, font=('Monospace', 9))
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.log_text, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom button frame
        btn_frame = ttk.Frame(frame, padding=(0, 10, 0, 0))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop scrcpy", command=self._stop_scrcpy)
        self.stop_btn.pack(side=tk.RIGHT)
        
        self.status_label = ttk.Label(btn_frame, text="scrcpy is running...")
        self.status_label.pack(side=tk.LEFT)
        
        # Start log reading thread
        self.thread = threading.Thread(target=self._read_output, daemon=True)
        self.thread.start()
        
        # Center dialog relative to parent window
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            dw = 600
            dh = 400
            cx = px + (pw // 2) - (dw // 2)
            cy = py + (ph // 2) - (dh // 2)
            self.geometry(f"+{max(0, cx)}+{max(0, cy)}")
        except Exception:
            pass
            
        # Start queue checking
        self._check_queue()
        self.bind('<Escape>', lambda e: self.destroy())



    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ''):
                if not line:
                    break
                self.queue.put(line)
        except Exception as e:
            self.queue.put(f"\n[Error reading output: {e}]\n")
        finally:
            self.queue.put(None) # Signal end

    def _check_queue(self):
        MAX_LINES = 1000
        while True:
            try:
                line = self.queue.get_nowait()
                if line is None:
                    self._on_process_end()
                    return
                
                self.log_text.insert(tk.END, line)
                
                line_count = int(self.log_text.index('end-1c').split('.')[0])
                if line_count > MAX_LINES:
                    lines_to_remove = line_count - MAX_LINES
                    self.log_text.delete('1.0', f'{lines_to_remove + 1}.0')

                self.log_text.see(tk.END)
            except queue.Empty:
                break

        
        if self.is_running:
            self.after(100, self._check_queue)

    def _on_process_end(self):
        self.is_running = False
        self.status_label.config(text="scrcpy has terminated.")
        self.stop_btn.config(text="Close", command=self.destroy)

    def _stop_scrcpy(self):
        if self.stop_callback:
            self.stop_callback(self.device_id)
        self.destroy()

    def _on_closing(self):
        # We don't necessarily want to kill scrcpy just by closing the window,
        # but the user said "add a stop scrcpy button which should terminate the process".
        # If they close the window via 'X', we might want to keep it running? 
        # Usually, if it's an output window, closing it might be fine, but the process continues.
        # However, to keep it simple and fulfill the "stop" requirement, I'll just destroy the window.
        self.is_running = False
        self.destroy()
