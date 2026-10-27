"""Device profiles: named setups of recordable actions, and their replay.

A setup is saved as {'name', 'steps'} in config 'profiles'/'setups'. The steps
come from the action registry's recordable entries plus the two special steps
the executor here implements itself: 'connect_wireless' (connect to a straight
address, no dialog) and 'start_mirroring' (only starts what is not running).
They are chosen with checkboxes rather than a full recording, and run from top
to bottom - connection, ticked actions, then mirroring.

Replay walks the steps on the UI thread with a short pause between them; each
action keeps its own dialogs and threads. Cancel stops the steps still to
come; a step already started runs out.
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .dpi import setup_window_dpi, scale_size
from .action_registry import RECORDABLE_ACTIONS, action_key, entry_for_key, SPECIAL_STEP_KEYS
from .error_detail_dialog import ErrorDetailDialog
from .scrcpy_overlay import ScrcpyOverlayToolbar

_CONNECT_WIRELESS, _START_MIRRORING = SPECIAL_STEP_KEYS

_CONFIG_MANAGER = None


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


def load_setups():
    """Saved setups [{'name', 'steps': [{'key', optional 'address'}]}]."""
    config = _config()
    loaded = config.get('profiles', 'setups', []) if config else []
    setups = []
    for entry in loaded or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('name') or '').strip()
        steps = []
        for item in entry.get('steps') or []:
            if isinstance(item, dict) and str(item.get('key') or '').strip():
                step = {'key': str(item['key']).strip()}
                if isinstance(item.get('address'), str) and item['address'].strip():
                    step['address'] = item['address'].strip()
                steps.append(step)
        if name and steps:
            setups.append({'name': name, 'steps': steps})
    return setups


def save_setups(setups):
    """Write the setup list back to config; False when storage is missing."""
    config = _config()
    if config is None:
        return False
    config.set('profiles', 'setups', setups)
    return True


def parse_address(raw: str):
    """'host' or 'host:port' -> (host, port); None when malformed.

    A bare address gets the classic 5555 port.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    host, port = raw, 5555
    if ':' in raw:
        host, _, port_text = raw.rpartition(':')
        host, port_text = host.strip(), port_text.strip()
        if not host or not port_text.isdigit():
            return None
        port = int(port_text)
        if not 0 < port <= 65535:
            return None
    return host, port


def step_label(step) -> str:
    """Human wording for one saved step, matching its label in the builder."""
    if isinstance(step, str):
        step = {'key': step}
    key = step.get('key') if isinstance(step, dict) else ''
    if key == _CONNECT_WIRELESS:
        return f"Connect Wirelessly ({step.get('address') or 'host[:port]'})"
    if key == _START_MIRRORING:
        return "Start Mirroring"
    entry = entry_for_key(key)
    return entry[1] if entry else f"Unknown step ({key})"


class StepsProgressDialog(tk.Toplevel):
    """Countdown-and-cancel window shown while saved steps replay."""

    def __init__(self, parent, kind: str, name: str, device_id: str,
                 total_steps: int, cancel_command):
        super().__init__(parent)
        noun = 'setup' if kind == 'setup' else 'macro'
        self.title(f"Running {noun}...")
        self.geometry("480x200")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text=f"Running {noun} '{name}' on '{device_id}' "
                       f"({total_steps} step(s))...",
                  font=('', 10, 'bold'), wraplength=410,
                  justify='left').pack(anchor='w', pady=(0, 8))

        self._stage = tk.StringVar(self, "Preparing the first step...")
        ttk.Label(frame, textvariable=self._stage, wraplength=410,
                  justify='left').pack(anchor='w', pady=(0, 10))

        self._bar = ttk.Progressbar(frame, mode='determinate',
                                    maximum=max(total_steps, 1))
        self._bar.pack(fill=tk.X)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Cancel",
                   command=cancel_command).pack(side=tk.RIGHT)
        ttk.Label(buttons,
                  text="Cancel stops the steps still to come; one already "
                       "started runs out.",
                  foreground='gray', font=('', 9, 'italic'), wraplength=280,
                  justify='left').pack(side=tk.LEFT)

        # No grab on purpose: the steps open their own dialogs (a power action
        # asks on screen first), and a grab would leave those unclickable.
        setup_window_dpi(self, base_width=480, base_height=190,
                         min_width=440, min_height=170, parent=parent)
        self.protocol("WM_DELETE_WINDOW", cancel_command)

    def set_stage(self, text: str):
        """Swap the line describing what the replay is doing right now."""
        try:
            self._stage.set(text)
        except tk.TclError:
            pass

    def set_step(self, value: int):
        """Move the bar along the number of steps dispatched so far."""
        try:
            self._bar.config(value=value)
        except tk.TclError:
            pass

    def close(self):
        """Take the window down (called from the UI thread)."""
        try:
            self.destroy()
        except tk.TclError:
            pass


class SetupStepsRunner:
    """Replays the steps of a saved setup or macro, in order, on the UI thread.

    Each step is one method call: actions run their own dialogs and threads,
    the two special steps connect or start mirroring directly. The pause
    between steps is scheduled with ``after`` so the interface stays
    responsive, and Cancel only stops the steps that have not started yet.
    """

    PAUSE_SECONDS = 3

    def __init__(self, window, kind: str, name: str, device_id: str, steps):
        self._window = window
        self._root = window.root
        self._noun = 'setup' if kind == 'setup' else 'macro'
        self._name = name
        self._device_id = device_id
        self._steps = self._normalize(steps)
        self._failures = []
        self._ran = 0
        self._cancelled = False
        self._countdown = 0
        self._pending = None
        self._after_job = None
        self._dialog = StepsProgressDialog(
            self._root, kind, name, device_id, len(self._steps),
            cancel_command=self.cancel)

        if not self._steps:
            self._finish()
            return
        self._dispatch(0)
        self._pace(1)

    def _normalize(self, steps):
        """Steps as {'key', optional 'address'}; macros save bare keys."""
        saved = []
        for step in steps or []:
            if isinstance(step, str):
                step = {'key': step}
            if not isinstance(step, dict):
                continue
            key = str(step.get('key') or '').strip()
            if not key:
                continue
            entry = {'key': key}
            address = step.get('address')
            if isinstance(address, str) and address.strip():
                entry['address'] = address.strip()
            saved.append(entry)
        return saved

    def cancel(self):
        """Stop the steps that have not started yet (safe to call anytime)."""
        self._cancelled = True

    # -- stepping -----------------------------------------------------------

    def _stage_text(self, index, tail=None):
        total = len(self._steps)
        label = step_label(self._steps[index])
        return f"Step {index + 1} of {total} - {label}" + (f" ({tail})" if tail else "")

    def _show_countdown(self):
        self._dialog.set_stage(self._stage_text(self._pending,
                                                f"next in {self._countdown} s"))

    def _pace(self, index):
        """Count down the fixed pause before starting step ``index``."""
        if self._cancelled or index >= len(self._steps):
            self._finish()
            return
        self._pending = index
        self._countdown = self.PAUSE_SECONDS
        self._show_countdown()
        self._after_job = self._root.after(1000, self._tick)

    def _tick(self):
        self._after_job = None
        if self._cancelled:
            self._finish()
            return
        if self._dialog is None or not self._dialog.winfo_exists():
            return
        self._countdown -= 1
        if self._countdown > 0:
            self._show_countdown()
            self._after_job = self._root.after(1000, self._tick)
            return
        index, self._pending = self._pending, None
        self._dispatch(index)
        self._pace(index + 1)

    def _dispatch(self, index):
        """Run one step right now; a failure line is kept for the summary."""
        total = len(self._steps)
        self._dialog.set_stage(self._stage_text(index))
        try:
            self._execute(self._steps[index])
        except Exception as e:
            label = step_label(self._steps[index])
            self._failures.append(f"Step {index + 1} of {total} ({label}): {e}")
        self._ran += 1
        self._dialog.set_step(index + 1)

    def _execute(self, step):
        """One step's dispatch, each special step its own direct path."""
        key = step['key']
        if key == _CONNECT_WIRELESS:
            parsed = parse_address(step.get('address', ''))
            if parsed is None:
                raise ValueError(
                    f"no usable address was given ('{step.get('address') or ''}')")
            host, port = parsed
            self._window.device_manager.connect_device(host, port)
        elif key == _START_MIRRORING:
            self._start_mirroring()
        else:
            entry = entry_for_key(key)
            if entry is None:
                raise ValueError(f"unknown action '{key}'")
            method_name, args = entry[2][0], entry[2][1:]
            getattr(self._window, method_name)(*args)

    def _start_mirroring(self):
        """Start mirroring for the replayed device when it is not running yet.

        Mirrors _toggle_mirroring's start branch: same settings, same overlay
        toolbar that carries the stop button, same error reporting on the
        thread that launches scrcpy.
        """
        device_id = self._device_id
        try:
            already = self._window.device_manager.scrcpy.is_mirroring(device_id)
        except Exception:
            already = False
        if already:
            self._window._set_status("Device is already mirroring - step skipped")
            return

        self._window._set_status("Starting screen mirroring...")

        def task():
            try:
                settings = dict(getattr(self._window, 'mirror_settings', {}))
                window_title = f"Droidmgr - {device_id}"
                settings['window_title'] = window_title

                process = self._window.device_manager.start_mirroring(
                    device_id, **settings)

                def start_overlay():
                    self._window._update_mirror_label(True)
                    self._window._set_status("Mirroring started")

                    def stop_cb(dev_id):
                        try:
                            self._window.device_manager.stop_mirroring(dev_id)
                        except Exception:
                            pass
                        self._window._update_mirror_label(False)
                        self._window._set_status("Mirroring stopped")

                    ScrcpyOverlayToolbar(
                        parent=self._root,
                        process=process,
                        device_id=device_id,
                        device_manager=self._window.device_manager,
                        stop_callback=stop_cb,
                        show_settings_callback=self._window._show_scrcpy_settings,
                        take_screenshot_callback=self._window._take_screenshot,
                        record_screen_callback=self._window._record_screen,
                        window_title=window_title,
                    )

                self._root.after(0, start_overlay)
            except Exception as e:
                msg = str(e)
                self._root.after(0, lambda: self._window._show_error(
                    "Mirroring Error", msg))

        threading.Thread(target=task, daemon=True).start()

    # -- outcome ------------------------------------------------------------

    def _finish(self):
        """End the run: report the outcome and take the progress window down."""
        if self._after_job is not None:
            try:
                self._root.after_cancel(self._after_job)
            except Exception:
                pass
            self._after_job = None
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

        total = len(self._steps)
        errors = len(self._failures)
        title = self._noun.title()
        error_part = (f", {errors} error" + ("s" if errors != 1 else "")
                      if errors else "")
        if self._cancelled and self._ran < total:
            message = (f"{title} '{self._name}' cancelled: {self._ran} of "
                       f"{total} step(s) done{error_part}")
        else:
            message = (f"{title} '{self._name}' finished: {total} "
                       f"step(s) done{error_part}")
        self._window._set_status(message)

        if self._failures:
            ErrorDetailDialog(
                self._root, f"{title} Finished With Errors",
                f"'{self._name}' finished with {errors} problem(s):",
                "\n".join(self._failures))


class DeviceProfilesDialog(tk.Toplevel):
    """Saved setups with run and delete, plus a builder for a new one."""

    def __init__(self, parent, run_callback, set_status_callback=None):
        super().__init__(parent)
        self.title("Device Profiles")
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

        list_frame = ttk.LabelFrame(main, text="Saved setups", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(list_frame, columns=('name', 'steps'),
                                 show='headings', selectmode='browse')
        self.tree.heading('name', text='Setup')
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
        ttk.Button(buttons, text="Run", command=self._run_selected).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Delete",
                   command=self._delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="New...", command=self._new_setup).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy,
                   width=10).pack(side=tk.RIGHT)

        self.summary_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self.summary_var,
                  foreground='gray').pack(anchor='w', pady=(8, 0))

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        self._entries = {}
        for entry in load_setups():
            item = self.tree.insert('', tk.END,
                                    values=(entry['name'], len(entry['steps'])))
            # Keyed by tree item id, which is what a selection reports.
            self._entries[item] = entry
        self.summary_var.set("No setups saved" if not self._entries
                             else f"{len(self._entries)} saved setup(s)")

    def _selected_entry(self):
        items = self.tree.selection()
        return self._entries.get(items[0]) if items else None

    def _run_selected(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo("Device Profiles",
                                "Select the saved setup to run first.", parent=self)
            return
        if self._run('setup', entry['name'], entry['steps']):
            self.destroy()

    def _delete_selected(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo("Device Profiles",
                                "Select the saved setup to delete first.", parent=self)
            return
        name = entry['name']
        if not messagebox.askyesno("Delete Setup",
                                   f"Delete the saved setup '{name}'?", parent=self):
            return
        if not save_setups([s for s in load_setups() if s['name'] != name]):
            messagebox.showerror("Delete Setup Failed",
                                 "No configuration storage is available.", parent=self)
            return
        self._refresh_list()
        self._set_status(f"Deleted setup '{name}'")

    def _new_setup(self):
        SetupBuilderDialog(self, on_saved=self._after_saved,
                           set_status_callback=self._set_status)

    def _after_saved(self, name, steps):
        self._refresh_list()
        self._set_status(f"Saved setup '{name}' ({len(steps)} step(s))")


class SetupBuilderDialog(tk.Toplevel):
    """Build one named setup from ticked actions plus the optional specials."""

    def __init__(self, parent, on_saved, set_status_callback=None):
        super().__init__(parent)
        self.title("New Device Setup")
        self._on_saved = on_saved
        self._set_status = set_status_callback or (lambda message: None)
        self._action_vars = []              # (entry, BooleanVar) in registry order

        self.resizable(False, False)
        self.transient(parent)

        self._create_widgets()

        setup_window_dpi(self, base_width=500, base_height=560,
                         min_width=470, min_height=520, parent=parent)

        self.bind('<Return>', lambda e: self._save())
        self.bind('<Escape>', lambda e: self.destroy())
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    def _create_widgets(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        name_frame = ttk.LabelFrame(main, text="Name", padding=10)
        name_frame.pack(fill=tk.X)
        name_frame.columnconfigure(1, weight=1)
        ttk.Label(name_frame, text="Setup name:").grid(row=0, column=0,
                                                       sticky='w', padx=(0, 6))
        self._name_var = tk.StringVar()
        name_entry = ttk.Entry(name_frame, textvariable=self._name_var)
        name_entry.grid(row=0, column=1, sticky='ew')
        name_entry.focus_set()

        steps_frame = ttk.LabelFrame(main, text="Actions", padding=10)
        steps_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        canvas = tk.Canvas(steps_frame, highlightthickness=0,
                           height=scale_size(220, self))
        scrollbar = ttk.Scrollbar(steps_frame, orient=tk.VERTICAL,
                                  command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(0, 2))
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for entry in RECORDABLE_ACTIONS:
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(inner,
                            text=f"{entry[0]} > {entry[1]}",
                            variable=var).pack(anchor='w', pady=1)
            self._action_vars.append((entry, var))

        extras = ttk.LabelFrame(main, text="Extra steps", padding=10)
        extras.pack(fill=tk.X, pady=(10, 0))
        extras.columnconfigure(1, weight=1)
        self._connect_var = tk.BooleanVar(value=False)
        connect_check = ttk.Checkbutton(extras, text="Connect wirelessly to:",
                                        variable=self._connect_var,
                                        command=self._toggle_address_entry)
        connect_check.grid(row=0, column=0, sticky='w')
        self._address_var = tk.StringVar()
        self._address_entry = ttk.Entry(extras, textvariable=self._address_var)
        self._address_entry.grid(row=0, column=1, sticky='ew', padx=(6, 6))
        self._address_entry.state(['disabled'])
        ttk.Label(extras, text="host[:port]", foreground='gray').grid(
            row=0, column=2, sticky='w')

        self._mirror_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(extras, text="Start Mirroring",
                        variable=self._mirror_var).grid(row=1, column=0,
                                                        sticky='w', pady=(8, 0))
        ttk.Label(extras, text="(no-op when the device already mirrors)",
                  foreground='gray').grid(row=1, column=1, columnspan=2,
                                          sticky='w', pady=(8, 0))

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Save", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel",
                   command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(main, text="Steps run top to bottom: wireless connect (if "
                  "ticked), the ticked actions, then mirroring.",
                  foreground='gray', font=('', 9, 'italic'), wraplength=460,
                  justify='left').pack(anchor='w', pady=(8, 0))

    def _toggle_address_entry(self):
        state = 'disabled' if not self._connect_var.get() else '!disabled'
        self._address_entry.state([state])

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showinfo("Save Setup", "Enter a name for the setup.",
                                parent=self)
            return

        steps = []
        if self._connect_var.get():
            parsed = parse_address(self._address_var.get())
            if parsed is None:
                messagebox.showinfo(
                    "Save Setup",
                    "The wireless address must be host or host:port - for "
                    "example 192.168.1.10.",
                    parent=self)
                return
            host, port = parsed
            steps.append({'key': _CONNECT_WIRELESS, 'address': f"{host}:{port}"})
        for entry, var in self._action_vars:
            if var.get():
                steps.append({'key': action_key(entry)})
        if self._mirror_var.get():
            steps.append({'key': _START_MIRRORING})
        if not steps:
            messagebox.showinfo("Save Setup",
                                "Tick at least one action or extra step.", parent=self)
            return

        if _config() is None:
            messagebox.showerror("Save Setup Failed",
                                 "No configuration storage is available.", parent=self)
            return

        setups = load_setups()
        existing = next((s for s in setups if s['name'] == name), None)
        if existing and not messagebox.askyesno(
                "Save Setup", f"Replace the existing setup '{name}'?", parent=self):
            return
        if existing:
            existing['steps'] = steps
        else:
            setups.append({'name': name, 'steps': steps})
        save_setups(setups)
        self._on_saved(name, steps)
        self.destroy()
