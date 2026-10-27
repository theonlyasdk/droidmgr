# Completed Features

Features that are in the app. When an item is picked from the proposals
(`docs/FEATURE_PROPOSALS.md`), it moves here once it is built and
smoke-checked, with pointers to where it lives in the code.

## Moved from the proposals (2026-10-27)

- **D4 – Wireless pairing.** Turned out to exist already when the proposal
  was picked up: the wireless dialog has a "Pair with Code (Android 11+)"
  tab (`wireless_pairing_tab.py`) running `adb pair` through
  `adb_wireless.pair_device`. No new work was needed.
- **A1 – Install options (pm flags).** The install confirm is now a real
  dialog (`src/ui/apk_install_options.py`) with the switches: replace `-r`
  (default on), allow downgrade `-d`, test-only `-t`, and a grant-all
  toggle. Flag building and the friendly `Failure [...]` parsing moved to
  core helpers (`_install_flags`, `_raise_install_failure` in
  `src/core/adb_apps.py`; `install_apk` takes the options dict).
  Grant-all reads the package name offline from the APK manifest
  (`inspect_apk`), parses `dumpsys package` requested permissions and runs
  `su -c pm grant` per permission; the outcome is reported as notes in the
  install result box (`APKInstallProgressDialog.finish` gained a `notes`
  section).
- **A2 – Split / bundled APK install.** `.xapk` and `.apks` bundles are
  unzipped to a temp dir (base APK first, cleanup guaranteed), and a
  dropped `base.apk` beside its `split_*.apk` files is auto-grouped; each
  group installs as one `adb install-multiple` call
  (`install_apk_set` in `src/core/adb_apps.py`, container/grouping helpers
  in `src/ui/main_app_actions.py`). Unrelated APKs still install one by
  one. The file picker offers `*.xapk *.apks`.
- **A3 – Uninstall variants.** `UninstallOptionsDialog`
  (`src/ui/uninstall_options.py`) collects "keep app data and cache"
  (`pm uninstall -k`) and "uninstall for every device user" (`--user all`);
  `uninstall_app` in `src/core/adb_apps.py` + `device_manager.py` takes
  both flags. Bulk failures now report each package's own error message,
  and a latent bug is fixed where cancelling the bulk confirm was ignored.
- **A4 – Permission manager.** App Info Dialog gained a "Runtime
  Permissions" tab (`src/ui/app_info_dialog.py`): granted/denied state
  loaded asynchronously from `dumpsys package`
  (`get_runtime_permissions` in `src/core/adb_apps.py`), read-only list
  until a row is selected, then Grant / Revoke via `pm grant` / `pm revoke`
  (audit-logged as `GRANT_PERMISSION` / `REVOKE_PERMISSION`).
- **A5 – Batch APK export.** Selecting several apps and using Extract pulls
  each package into one folder (`extract_many` in `src/ui/apk_extract.py`),
  reports any per-package failure with its message, and offers to zip all
  extracted files into one archive. The single-app flow is unchanged.
- **F2 – Remote text-file editor round-trip.** "Edit..." on a single likely-text
  file (extension allow-list, <= 2 MB) in the Files tab pulls it to a local
  edit copy (`src/ui/file_ops.py`), opens it with the OS default editor, and
  an mtime/size watcher (3 s poll) offers to push the file back through the
  existing upload when it changes. "Stop Watching '<name>'" in the context
  menu — or answering No once — ends the watching. List and grid views share
  the context menu.
- **F3 – Storage usage bars.** After each listing, a best-effort background
  `du` pass (`get_dir_sizes` in `src/core/adb_files.py`) writes directory
  sizes into the existing Size column, and `df` free space feeds a light
  summary strip (Folder total + Storage free) on top of the Files tab
  (`src/ui/file_listing.py`, `src/ui/file_manager.py`). Failures leave the
  values blank; no dialogs by design.
- **F4 – Path favorites & history.** The path bar has a pin button and a
  drop-down listing favorites (starred) and recent paths, stored per device
  via ConfigManager (`src/ui/file_manager.py`), deduped with history capped
  at 15; choosing an entry navigates exactly like typing the path.
- **N1 – Per-table export.** The Network toolbar gained "Export Rows...":
  one Save As dialog per tab writes the visible table straight from its
  cached `raw_rows` — no device re-query. CSV (`csv.DictWriter`, columns
  from the first row, rows in capture order) or JSON follows the chosen
  extension (`src/ui/network_export.py`, button in `network_panels.py`'s
  toolbar); an empty table shows a friendly info message instead, and the
  status bar reports the row count and path.
- **N4 – Forwarding sets.** The forwarding dialog (`src/ui/forward_dialog.py`)
  keeps its existing forward/reverse row handling and gains a "Saved sets"
  section: named presets of `{local, remote, type}` rows stored via
  ConfigManager (`forwards` section, lists validated like the shell presets
  in `src/core/config_manager.py`). "Save set..." snapshots the device's
  active rules, "Apply set..." re-adds every row through the existing add
  machinery and reports per-row failures at the end, "Delete set..." removes
  a preset; sets are device-agnostic so they can be reused across devices.
- **B3 – Sideload OTA.** Device menu > "Apply Update From File...": pick a
  signed zip (existence, non-empty, PK-zip magic — `validate_sideload_package`
  in `src/core/adb_devices.py`), an offer to reboot into the `sideload`
  state when the device is not there (with an automatic wait, up to 120 s),
  a confirm of the apply itself, then `adb sideload` streams the package
  while the percentage adb prints drives a determinate bar
  (`sideload_package` with progress callbacks; window in
  `src/ui/sideload_progress_dialog.py`, flow in `src/ui/main_mirror.py`).
  Success offers a reboot back into Android; failures show adb's console in
  a copyable detail box. Audit-logged as `ADB_SIDELOAD` / `ADB_SIDELOAD_FAILED`.
- **B5 – Post-flash choices.** The plain "Reboot the device now?" after a
  successful flash became a three-way dialog (`src/ui/post_flash_dialog.py`):
  reboot into Android, test-boot the image once (`fastboot boot <img>` runs
  it from memory without writing anything — boot-magic validation and
  fastboot membership checked in `adb_devices.fastboot_boot`), or leave the
  device in the bootloader.
- **B6 – Bootloader pre-flight.** Before the write is confirmed — and again,
  once a device that needed a reboot first actually reaches the bootloader —
  the flashing flow reads `fastboot getvar unlocked` and
  `fastboot flashing get_unlock_ability` (`fastboot_getvar` /
  `fastboot_get_unlock_ability` in `src/core/adb_devices.py`, proxied by
  DeviceManager). A locked bootloader gets a blocking warning that mentions
  what the state means (get_unlock_ability 0 = 'OEM unlocking' not enabled)
  and defaults to cancelling the flash; an unreadable state continues
  without nagging.
- **M3 – Screenshot gallery.** Every screenshot saved to disk during this
  run of the app registers in a session gallery (`src/ui/screenshot_gallery.py`,
  hook when a save completes in `capture_screenshot.py`): newest-first
  thumbnail grid (Tk PhotoImage, captions show file + device id), double-click
  opens the file, a context menu copies / opens / reveals it, the toolbar
  offers "Save All..." (folder picker, conflicts suffixed) and "Send to
  Device..." (device combobox, uploads to `/sdcard/Pictures` through the
  Files tab's upload). Menu: Device > "Screenshot Gallery..." (method in
  `src/ui/main_diag.py`).
- **C2 – Dropbox (crash) browser.** Device menu > "Crash & ANR Browser...":
  a modal over `dumpsys dropbox --print` parsed off-thread (`dropbox_entries`
  in `src/core/adb_dropbox.py`, a module joined into the ADBManager compose
  chain; delegated by DeviceManager). Entries newest-first in a
  `_SortableTree` Network-tab-style table (Tag, local time, bytes) with a
  tag filter combo and a raw detail pane (full text copyable, display
  capped at 500 KB per entry, 400 entries / 300 KB per blob parse cap).
- **W1 – Shell console tab.** A "Console" tab after Network
  (`src/ui/console_tab.py`): command entry with a persisted history combo
  (25 newest, ConfigManager `console.history`, validated), one-liner
  shortcut buttons (`dumpsys battery`, `svc wifi/data enable/disable`),
  monospace output pane with per-run headers, Copy/Clear, and a 200 KB
  display cap. Every run confirms the exact command per device first
  (default No), runs on a daemon thread through the existing
  `run_shell_command`, and audit-logs as `CONSOLE_COMMAND`.
- **W2 – Device profiles (setups).** Tools menu > "Device Profiles..."
  (`src/ui/device_profiles.py`): named setups built from a checkbox
  suggestion list of the recordable actions plus two specials
  (`connect_wireless` with an optional address row, `start_mirroring`
  start-only), persisted via ConfigManager (`profiles.setups`, validated).
  Run re-executes the steps on the UI thread at a paced 3 s clip in a
  cancellable progress window and reports per-step failures in a summary
  box.
- **W3 – Action macros.** Tools menu > "Toggle Macro Recording" captures
  clicks of the recordable actions (`src/ui/macro_recorder.py` wraps the
  registry methods once; the `_refresh_devices` poll noise is filtered from
  capture by design), then names and saves them (`macros.macros`,
  validated); "Macros..." lists saved macros to Replay / Delete. Recorded
  actions keep their native dialogs (e.g. power confirmations) so replay is
  never silent, and replay is refused while recording is on.
- **X2 – Command palette.** Help menu > "Command Palette (Ctrl+K)"
  (`src/ui/command_palette.py`, bound in `main_menu.py`): fuzzy search
  (substring then subsequence scoring) over the whole menubar tree with
  menu paths, plus the registry-only actions; Enter/double-click invokes
  the entry exactly like the menu itself, disabled entries are listed but
  marked; an open palette refocuses instead of stacking.
- **X3 – Tool version guards.** The adb and fastboot platform-tools
  versions are read once per session at the first device refresh
  (`get_tool_versions` beside `get_fastboot_devices` in
  `src/core/adb_devices.py`, delegated by DeviceManager); when their
  major.minor differs — or fastboot is unreadable while adb works — a
  dismissable warning banner with both versions appears above the Devices
  tab's device list (`src/ui/main_devices.py`); matching versions stay
  silent.
- **X4 – First-run checklist.** A "Getting started" card above the device
  list, packed only when the last refresh's data says something needs
  saying: adb missing (button -> the Preferences dialog's tool selection),
  no devices (plug in / USB debugging / approve RSA + Refresh), or devices
  in a non-ready state (unauthorized: approve the prompt; offline: replug /
  Reconnect ADB; fastboot: neutral hint). It never queries the device — it
  maps the data the refresh already collected.
- **M4 – Wireless mirror.** Device menu > "Wireless Mirror..." is the
  one-stop path for a device whose address is already known
  (`src/ui/wireless_mirror_dialog.py`): the last address is remembered per
  device via ConfigManager (`wireless_mirror` section), "Connect & Mirror"
  runs `adb connect` first and then starts scrcpy against that connection
  with the normal mirror settings and overlay toolbar. Pairing and the
  TCP/IP switch stay in the fuller "Connect Wirelessly..." dialog.

## Completed earlier in 2026-10 (picked up directly, not via the proposals)

- **Fastboot flash pipeline.** Device menu > "Flash Recovery Image..." —
  file choice, combined validation (fastboot presence, image file, boot-image
  magic), fastboot-mode check with an offer to reboot into the bootloader
  and an automatic wait, final confirm, progress window, elapsed-time
  outcome, reboot question, and copyable error output
  (`flash_fastboot_image` / `validate_flash_image` in
  `src/core/adb_devices.py`, flow in `src/ui/main_mirror.py`,
  `flash_progress_dialog.py`, `error_detail_dialog.py`).
- **Wireshark-style Network tab.** Packet-list styling (dense striped rows,
  blue selection, coloring rules), live display filter with the white /
  yellow / green / red tint, "N of M shown" counter, per-tab empty states,
  stop/start polling toggle (`src/ui/network_tables.py`,
  `network_panels.py`, `network_polling.py`).
- **APK install lifecycle.** Confirm plus one dialog covering the whole
  install: indeterminate progress while busy, then elapsed duration and a
  scrollable, copyable outcome box (`src/ui/apk_install_progress.py`,
  `_install_apk_paths` in `src/ui/main_app_actions.py`).
- **Applications tab loading/empty states and faster icons.** Indeterminate
  bar until the first app loads, offline/empty texts, up to three
  concurrent icon workers with visible-tile priority
  (`src/ui/main_apps.py`, `main_app_grid.py`, `main_app_icons.py`,
  `src/core/adb_icons.py`).
- **Status bar collapse fix and apps toolbar layout parity.** The status
  bar stays visible when the window shrinks; apps-tab toolbar matches the
  Files tab ordering (`src/ui/main_window.py`, `src/ui/main_apps.py`).
