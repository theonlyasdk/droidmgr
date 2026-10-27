"""MainWindow mixin: device profiles (named setups) and the macro recorder.

The menus (main_menu.py) call the three public names here: _show_device_profiles,
_toggle_macro_recording and _show_macro_dialog. Both replays funnel through
_run_saved_steps, which confirms and then hands the steps to the executor in
device_profiles.py used by setups and macros alike.
"""

from tkinter import messagebox

from . import macro_recorder
from .device_profiles import DeviceProfilesDialog, SetupStepsRunner
from .macro_recorder import MacroListDialog


class _ProfilesMixin:
    """_ProfilesMixin for MainWindow (see main_window.py)."""

    # -- device profiles (W2) --------------------------------------------

    def _show_device_profiles(self):
        """Open the manager for the saved named setups."""
        DeviceProfilesDialog(self.root,
                             run_callback=self._run_saved_steps,
                             set_status_callback=self._set_status)

    # -- macro recorder (W3) ----------------------------------------------

    def _toggle_macro_recording(self):
        """Start or stop macro recording; stopping offers to save what ran."""
        if getattr(self, '_macro_recording', False):
            self._stop_macro_recording()
        else:
            self._start_macro_recording()

    def _start_macro_recording(self):
        if not macro_recorder.start_recording(self):
            self._set_status("Already recording a macro")
            return
        self._set_status("Recording macro - click actions to capture them")

    def _stop_macro_recording(self):
        """Restore the wrapped methods and offer to save what was captured."""
        captured = macro_recorder.stop_recording(self)
        if not captured:
            self._set_status("Nothing was recorded")
            return
        macro_recorder.MacroSaveDialog(self.root, captured,
                                       on_saved=self._on_macro_saved,
                                       on_discarded=self._on_macro_discarded)

    def _on_macro_saved(self, name, steps):
        self._set_status(f"Macro saved ({len(steps)} step(s)) as '{name}'")

    def _on_macro_discarded(self):
        self._set_status("Macro recording ended - nothing saved")

    def _show_macro_dialog(self):
        """Open the saved-macro list with replay and delete."""
        MacroListDialog(self.root,
                        run_callback=self._run_saved_steps,
                        set_status_callback=self._set_status)

    # -- shared replay ------------------------------------------------------

    def _run_saved_steps(self, kind, name, steps):
        """Confirm and replay a saved setup or macro on the selected device.

        Returns True when the run was started, False when the user declined
        or there is nothing to replay it on.
        """
        if getattr(self, '_macro_recording', False):
            # Replayed steps would be captured by the wrappers as well, and
            # a recording only wants deliberate clicks.
            self._set_status("Stop macro recording before running a setup or macro")
            return False
        if not self._require_device():
            return False
        device_id = self.selected_device
        noun = 'setup' if kind == 'setup' else 'macro'
        if not messagebox.askyesno(
                f"Run {noun.title()}",
                f"Run {noun} '{name}' ({len(steps)} steps) on '{device_id}'?",
                parent=self.root):
            return False
        SetupStepsRunner(self, kind, name, device_id, steps)
        return True
