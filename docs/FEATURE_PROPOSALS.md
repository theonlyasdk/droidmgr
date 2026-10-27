# Feature Proposals

Ideas for future work on droidmgr, grounded in what the app already has. This
is a menu, not a promise: pick items, argue about them, and delete freely.
Effort ratings assume the current codebase shape (MainWindow mixins on the UI
side, ADBManager mixins in `src/core/`).

Legend: effort **S** (a session, one mixin/dialog) · **M** (a few sessions,
new state to manage) · **L** (a project of its own).

Picked items move to `docs/COMPLETED_FEATURES.md` once they are built.

---

## Device management

| # | Feature | Effort |
|---|---------|--------|
| D1 | **Device aliases / nicknames** | S |
| D2 | **Multi-device batch actions** | M |
| D3 | **Connect / disconnect watcher** | S |
| D5 | **Health history graphs** | M |

- **D1 – Device aliases.** Nicknames for serials stored via ConfigManager and
  shown everywhere the ID is (`main_devices.py` rows, menus, dialogs, audit log
  is already keyed by ID). Real serials are noise at three devices or more.
- **D2 – Multi-device batch actions.** Ctrl-click several devices and run one
  command against all of them: install the same APK, reboot, connect wireless
  to the same subnet host. Wire into `_require_device`-style guards with a
  progress dialog per batch (the APK install dialog already handles a list of
  targets structurally).
- **D3 – Connect / disconnect watcher.** The refresh loop already computes the
  set of serials each pass; diff consecutive passes and surface "left/arrived"
  as a status-bar flash or taskbar notification instead of relying on the user
  noticing the list change.
- **D5 – Health history.** `get_health_stats` currently reports a point in
  time. Poll it at a slow interval into a per-device ring buffer and draw a
  sparkline (battery %, temperature) in the device details dialog; feed the
  same buffer to the existing report export.

## Files

| # | Feature | Effort |
|---|---------|--------|
| F1 | **Transfer queue with progress** | M |

- **F1 – Transfer queue.** Multi-file/directory pushes and pulls currently
  ride one call. Queue them with per-item progress parsed from adb's own
  output, cancel-before-start, and a errors-at-the-end box (the install
  dialog's failure list is the template).

## Network

| # | Feature | Effort |
|---|---------|--------|
| N2 | **Saved display filters** | S |
| N3 | **Ping history sparklines** | M |

The Wireshark redo landed the display model (cached raw rows, filter, tint);
these ride on it.

- **N2 – Saved filters.** Recent and named filter expressions in a combo
  beside the entry bar, persisted in config — plain text snippets only, no
  query language.
- **N3 – Ping sparklines.** The ping table already tags degraded/dropped
  hosts; keep a per-host list of recent RTTs and draw a tiny inline trend on
  selection.

## Flashing

| # | Feature | Effort |
|---|---------|--------|
| B1 | **More partitions & flags** | S |
| B2 | **A/B slot awareness** | M |
| B4 | **Drag-and-drop flashing** | S |

The fastboot flash pipeline (validation → confirm → progress → result) from
October is the base everything here reuses; sideload, the post-flash
test-boot and the unlock pre-flight have already landed from this group.

- **B1 – Partitions & flags.** `_FLASHABLE_BOOT_PARTITIONS` is a module-level
  frozenset; add `vendor_boot`, `dtbo`, `vbmeta` with a per-partition warning,
  and optional flags (`--disable-verity`, `--disable-verification` for
  vbmeta) chosen in the confirm dialog.
- **B2 – Slots.** A/B devices flash to the active slot blindly today. Read
  `fastboot getvar current-slot` before flashing, show it in the confirm, and
  optionally flash the *inactive* slot then suggest `set_active` — much safer
  against a bad recovery image.
- **B4 – Drag and drop.** Drop an `.img` on the Devices tab: same validation
  dialog as picking a file, then route straight into
  `_flash_boot_partition_image` (partition inferred: filename or a chooser).
  Mirrors the APK drag-drop pattern.

## Mirroring & capture

| # | Feature | Effort |
|---|---------|--------|
| M1 | **Tiled multi-device mirroring** | M |
| M2 | **Recording presets & GIF export** | M |

- **M1 – Tiled mirroring.** Launch scrcpy for several selected devices with
  geometry-presets (half screen, quarter grid). scrcpy is already per-device
  via `scrcpy_manager`; this is orchestration + saved layouts.
- **M2 – Recording.** Screen recording runs device-side `screenrecord`
  (capture_record.py). Add quality presets on top of the existing parameter
  dialog, and an mp4→GIF conversion step (ffmpeg binary if present, offered
  in the done-dialog).

## Diagnostics & logs

| # | Feature | Effort |
|---|---------|--------|
| C1 | **Crash / ANR watcher** | M |
| C3 | **Build report for this bug** | S |

- **C1 – Crash watcher.** The logcat stream (`adb_shell.get_logcat`) already
  flows into the UI; add a regex pass over the lines for `FATAL EXCEPTION`,
  `ANR in`, and raise a small non-modal popup with the stacktail and Copy —
  optional per device, since it is noisy on default ROM builds.
- **C3 – Bug bundle one-click.** Bundle the bugreport + a health snapshot +
  the last 100 audit lines into one folder and open it, feeding the existing
  report/export tools.

## App infrastructure / UX

| # | Feature | Effort |
|---|---------|--------|
| X1 | **Dark theme** | M |

- **X1 – Dark theme.** The Wireshark styling work pinned exact colors into
  module-level constants in several files; to theme them move to a
  `theme.py` palette (a mechanical rename) then ship a dark palette next to
  the light one.

---

## Suggested first picks

Not authoritative — a starting point sized for small, independent sessions:

1. **B1** more flash partitions + **B4** drag-and-drop — both are small and
   complete the flashing feature that just landed.
2. **N2** network saved filters — rides directly on the Wireshark work.
3. **D3** connect watcher and **D1** aliases — small, noticed daily.
4. Then one **M**-effort item of the user's choosing (**F1** transfers or
   **C1** crash watcher are the highest-use candidates).
