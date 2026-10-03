"""Shell command history, saved presets and output-pane helpers."""
"""Split from shell_view.py (MOVE-ONLY); ShellView mixes this in."""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from core import ConfigManager

MAX_OUTPUT_LINES = 5000

MAX_HISTORY = 500


class ShellPresetsMixin:
    """Shell history, presets and output pane."""

    # -- history ---------------------------------------------------------
    def _record_history(self, command: str):
        if not self.history or self.history[-1] != command:
            self.history.append(command)
            if len(self.history) > MAX_HISTORY:
                del self.history[:len(self.history) - MAX_HISTORY]
        self.history_index = len(self.history)

    def _history_prev(self, event=None):
        if not self.history:
            return 'break'
        if self.history_index > 0:
            self.history_index -= 1
        self.command_var.set(self.history[self.history_index])
        return 'break'

    def _history_next(self, event=None):
        if not self.history:
            return 'break'
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.command_var.set(self.history[self.history_index])
        else:
            self.history_index = len(self.history)
            self.command_var.set('')
        return 'break'

    # -- presets ---------------------------------------------------------
    def _load_presets(self):
        presets = []
        for item in self.config.get('shell', 'presets', []) or []:
            name = str(item.get('name', '')).strip()
            command = str(item.get('command', '')).strip()
            if name and command:
                presets.append({'name': name, 'command': command})
        return presets

    def _refresh_presets(self):
        presets = self._load_presets()
        self.preset_combo.configure(values=[p['name'] for p in presets])
        if self.preset_var.get() not in [p['name'] for p in presets]:
            self.preset_var.set('')

    def _on_preset_selected(self, event=None):
        preset = self._selected_preset()
        if preset:
            self.command_var.set(preset['command'])
        self._update_controls()

    def _selected_preset(self):
        name = self.preset_var.get().strip()
        for preset in self._load_presets():
            if preset['name'] == name:
                return preset
        return None

    def _run_preset(self):
        preset = self._selected_preset()
        if not preset:
            self._show_error("Shell", "Select a preset first, or save the current command as one.")
            return
        self.command_var.set(preset['command'])
        self._submit()

    def _save_preset(self):
        command = self.command_var.get().strip()
        if not command:
            self._show_error("Save Preset", "Type the command to save in the input box first.")
            return
        name = simpledialog.askstring(
            "Save Preset", "Preset name:", parent=self.frame,
            initialvalue=self.preset_var.get().strip())
        if not name or not name.strip():
            return
        name = name.strip()
        presets = self._load_presets()
        existing = next((p for p in presets if p['name'] == name), None)
        if existing:
            if not messagebox.askyesno(
                    "Save Preset", f"Replace the existing preset '{name}'?", parent=self.frame):
                return
            existing['command'] = command
        else:
            presets.append({'name': name, 'command': command})
        self.config.set('shell', 'presets', presets)
        self._refresh_presets()
        self.preset_var.set(name)
        self._set_status(f"Saved shell preset '{name}'")

    def _delete_preset(self):
        name = self.preset_var.get().strip()
        if not name:
            self._show_error("Delete Preset", "Select the preset to delete first.")
            return
        if not messagebox.askyesno(
                "Delete Preset", f"Delete preset '{name}'?", parent=self.frame):
            return
        presets = [p for p in self._load_presets() if p['name'] != name]
        self.config.set('shell', 'presets', presets)
        self._refresh_presets()
        self._set_status(f"Deleted shell preset '{name}'")

    # -- output pane -----------------------------------------------------
    def clear(self):
        self._clear_view()
        self._set_status("Shell output cleared")
        self._update_status()

    def _export(self):
        if not self.output_text.get('1.0', tk.END).strip():
            self._show_error("Export Shell Output", "There is no shell output to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export Shell Output",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8', errors='replace') as out:
                out.write(self.output_text.get('1.0', tk.END))
            self._set_status(f"Exported shell output to {path}")
        except OSError as exc:
            self._show_error("Export Shell Output", f"Could not write file:\n{exc}")

    def _append_line(self, line: str, tag=None):
        try:
            self.output_text.configure(state=tk.NORMAL)
            if tag:
                self.output_text.insert(tk.END, line + '\n', tag)
            else:
                self.output_text.insert(tk.END, line + '\n')
            self.displayed_count += 1
            # Trim the widget to bound memory on long sessions.
            widget_lines = int(self.output_text.index('end-1c').split('.')[0])
            if widget_lines > MAX_OUTPUT_LINES + 500:
                self.output_text.delete('1.0', f'{widget_lines - MAX_OUTPUT_LINES}.0')
                self.displayed_count = MAX_OUTPUT_LINES
            self.output_text.configure(state=tk.DISABLED)
            self.output_text.see(tk.END)
        except Exception:
            pass

    def _clear_view(self):
        try:
            self.output_text.configure(state=tk.NORMAL)
            self.output_text.delete('1.0', tk.END)
            self.output_text.configure(state=tk.DISABLED)
        except Exception:
            pass
        self.displayed_count = 0
