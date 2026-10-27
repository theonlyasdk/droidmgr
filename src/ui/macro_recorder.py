"""Macro recorder: capture recordable menu actions into a named macro.

While recording, one-time setattr wrappers sit on the MainWindow methods the
action registry marks recordable (grouped by method; _power_action covers all
four of its reboot/power entries). A call passes through to the original and,
when the recording flag on the window is still up, appends its action key -
the exception the original raises is never swallowed.

Stopping restores the originals and opens the save dialog. Macros store plain
action keys ('macros'/'macros'), so the replay uses the same step executor
the device profiles use; the specials ('connect_wireless', 'start_mirroring')
are deliberately not recordable, which keeps macros to actions alone.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from .dpi import setup_window_dpi, scale_size
from .action_registry import RECORDABLE_ACTIONS, action_key, entry_for_key

_CONFIG_MANAGER = None

# The periodic device poll and many actions' completion callbacks run
# _refresh_devices on their own, so captures of it would only be noise;
# a setup can still include "Refresh Devices" deliberately.
_NOT_RECORDED_METHODS = {'_refresh_devices'}


def _config():
    """The shared ConfigManager, None when no configuration can be opened."""
    global _CONFIG_MANAGER
    if _CONFIG_MANAGER is None:
        try:
            from core.config_manager import ConfigManager
            _CONFIG_MANAGER = ConfigManager()
        except Exception:
            return None
    return _CONFIG_MANAGER


def load_macros():
    """Saved macros [{'name', 'steps': [key, ...]}], malformed rows dropped."""
    config = _config()
    loaded = config.get('macros', 'macros', []) if config else []
    macros = []
    for entry in loaded or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('name') or '').strip()
        steps = [key.strip() for key in (entry.get('steps') or [])
                 if isinstance(key, str) and key.strip()]
        if name and steps:
            macros.append({'name': name, 'steps': steps})
    return macros


def save_macros(macros):
    """Write the macro list back to config; False when storage is missing."""
    config = _config()
    if config is None:
        return False
    config.set('macros', 'macros', macros)
    return True


def call_key(method_name, args):
    """The registry key a recorded call stands for, None for unknown calls."""
    args = tuple(str(arg) for arg in args)
    for entry in RECORDABLE_ACTIONS:
        spec = entry[2]
        if spec[0] == method_name and spec[1:] == args:
            return action_key(entry)
    return None


def step_label(key):
    """The action's menu wording, or a placeholder for a stale key."""
    entry = entry_for_key(key)
    return entry[1] if entry else f"Unknown step ({key})"


# -- recording -----------------------------------------------------------

def start_recording(window) -> bool:
    """Install the recording wrappers; False when one is already running."""
    if getattr(window, '_macro_recording', False):
        return False
    captured = []
    originals = {}

    def wrapper(method_name, original):
        def wrapped(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                # The flag is read late, so stopping mid-call is honoured.
                if (getattr(window, '_macro_recording', False)
                        and not kwargs):
                    key = call_key(method_name, args)
                    if key is not None and not (
                            key.split(':', 1)[0] in _NOT_RECORDED_METHODS):
                        captured.append(key)
        return wrapped

    for method_name in sorted({entry[2][0] for entry in RECORDABLE_ACTIONS}):
        original = getattr(window, method_name, None)
        if original is None:
            continue
        originals[method_name] = original
        setattr(window, method_name, wrapper(method_name, original))

    window._macro_recording = True
    window._macro_buffer = captured
    window._macro_originals = originals
    return True


def stop_recording(window) -> list:
    """Take the wrappers off and return the keys captured while recording."""
    window._macro_recording = False
    for method_name, original in getattr(window, '_macro_originals', {}).items():
        try:
            setattr(window, method_name, original)
        except Exception:
            pass
    captured = list(getattr(window, '_macro_buffer', []) or [])
    window._macro_originals = {}
    window._macro_buffer = []
    return captured


# -- save dialog ---------------------------------------------------------

class MacroSaveDialog(tk.Toplevel):
    """Name and save (or discard) the steps captured by one recording."""

    def __init__(self, parent, captured_keys, on_saved, on_discarded=None):
        super().__init__(parent)
        self.title("Save Macro")
        self._captured = list(captured_keys)
        self._on_saved = on_saved
        self._on_discarded = on_discarded or (lambda: None)

        self.resizable(False, False)
        self.transient(parent)

        self._create_widgets()

        setup_window_dpi(self, base_width=430, base_height=330,
                         min_width=400, min_height=300, parent=parent)

        self.bind('<Return>', lambda e: self._save())
        self.bind('<Escape>', lambda e: self._discard())
        self.protocol('WM_DELETE_WINDOW', self._discard)

    def _create_widgets(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Recorded {len(self._captured)} action(s).",
                  font=('', 10, 'bold')).pack(anchor='w', pady=(0, 6))

        box = ttk.Frame(main)
        box.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        text = tk.Text(box, height=6, wrap='word', font=('', 9),
                       state=tk.DISABLED)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(box, orient=tk.VERTICAL, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)
        text.config(state=tk.NORMAL)
        for index, key in enumerate(self._captured, start=1):
            text.insert(tk.END, f"{index}. {step_label(key)}\n")
        text.config(state=tk.DISABLED)

        name_frame = ttk.Frame(main)
        name_frame.pack(fill=tk.X)
        name_frame.columnconfigure(1, weight=1)
        ttk.Label(name_frame, text="Macro name:").grid(row=0, column=0,
                                                       sticky='w', padx=(0, 6))
        self._name_var = tk.StringVar()
        entry = ttk.Entry(name_frame, textvariable=self._name_var)
        entry.grid(row=0, column=1, sticky='ew')
        entry.focus_set()

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Save", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Discard",
                   command=self._discard).pack(side=tk.RIGHT, padx=(6, 0))

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showinfo("Save Macro", "Enter a name for the macro.",
                                parent=self)
            return
        if _config() is None:
            messagebox.showerror("Save Macro Failed",
                                 "No configuration storage is available.", parent=self)
            return
        macros = load_macros()
        existing = next((m for m in macros if m['name'] == name), None)
        if existing and not messagebox.askyesno(
                "Save Macro", f"Replace the existing macro '{name}'?", parent=self):
            return
        if existing:
            existing['steps'] = list(self._captured)
        else:
            macros.append({'name': name, 'steps': list(self._captured)})
        save_macros(macros)
        try:
            self._on_saved(name, self._captured)
        finally:
            self.destroy()

    def _discard(self):
        try:
            self._on_discarded()
        finally:
            self.destroy()


# -- replay / manage ------------------------------------------------------

class MacroListDialog(tk.Toplevel):
    """Saved macros with replay and delete; recording is toggled from the menu."""

    def __init__(self, parent, run_callback, set_status_callback=None):
        super().__init__(parent)
        self.title("Macros")
        self._run = run_callback            # callable(kind, name, steps) -> bool
        self._set_status = set_status_callback or (lambda message: None)
        self._entries = {}

        self.resizable(True, True)
        self.transient(parent)

        self._create_widgets()
        self._refresh_list()

        setup_window_dpi(self, base_width=460, base_height=340,
                         min_width=420, min_height=300, parent=parent)

        self.bind('<Escape>', lambda e: self.destroy())
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    def _create_widgets(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        list_frame = ttk.LabelFrame(main, text="Saved macros", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(list_frame, columns=('name', 'steps'),
                                 show='headings', selectmode='browse')
        self.tree.heading('name', text='Macro')
        self.tree.heading('steps', text='Steps')
        self.tree.column('name', width=scale_size(280, self), anchor='w')
        self.tree.column('steps', width=scale_size(90, self), anchor='center')
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Replay",
                   command=self._replay_selected).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Delete",
                   command=self._delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Close", command=self.destroy,
                   width=10).pack(side=tk.RIGHT)

        self.summary_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self.summary_var,
                  foreground='gray').pack(anchor='w', pady=(8, 0))

        # Safety note: every recorded action still runs its own dialogs,
        # so a replay asks the same questions the menu actions do.
        ttk.Label(main, text="Replayed actions keep their usual dialogs - "
                  "power actions still ask before rebooting or shutting down, "
                  "and automatic device refreshes are not captured.",
                  foreground='gray', font=('', 9, 'italic'), wraplength=420,
                  justify='left').pack(anchor='w', pady=(8, 0))

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        self._entries = {}
        for entry in load_macros():
            item = self.tree.insert('', tk.END,
                                    values=(entry['name'], len(entry['steps'])))
            # Keyed by tree item id, which is what a selection reports.
            self._entries[item] = entry
        self.summary_var.set("No macros saved" if not self._entries
                             else f"{len(self._entries)} macro(s) saved")

    def _selected_entry(self):
        items = self.tree.selection()
        return self._entries.get(items[0]) if items else None

    def _replay_selected(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo("Macros",
                                "Select the saved macro to replay first.", parent=self)
            return
        if self._run('macro', entry['name'], entry['steps']):
            self.destroy()

    def _delete_selected(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo("Macros",
                                "Select the saved macro to delete first.", parent=self)
            return
        name = entry['name']
        if not messagebox.askyesno("Delete Macro",
                                   f"Delete the saved macro '{name}'?", parent=self):
            return
        if not save_macros([m for m in load_macros() if m['name'] != name]):
            messagebox.showerror("Delete Macro Failed",
                                 "No configuration storage is available.", parent=self)
            return
        self._refresh_list()
        self._set_status(f"Deleted macro '{name}'")
