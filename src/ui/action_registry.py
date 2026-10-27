"""Central registry of MainWindow actions for the palette and the macro recorder.

One module owns the list so the command palette (X2) and the macro recorder
(W3) describe the same actions with the same labels as the menus. An entry
is (category, label, spec, recordable):

- category   grouping shown as "Category > Label" paths everywhere
- label      the menu wording, where the action has a menu entry
- spec       how to call it: (method_name, *args) on MainWindow
- recordable True only for actions that run standalone, without wanting
             more input the device must give *later*; only these may be
             recorded into a macro or used as a profile step.
"""

ACTIONS = [
    # Devices tab
    ('Devices', 'Refresh Devices', ('_refresh_devices',), True),
    ('Devices', 'Check Root Access', ('_check_root_access',), True),
    ('Devices', 'Reconnect ADB', ('_reconnect_adb',), True),
    ('Devices', 'Disconnect Wireless Device', ('_disconnect_wireless_device',), True),

    # Power
    ('Device', 'Reboot', ('_power_action', 'reboot'), True),
    ('Device', 'Reboot to Recovery', ('_power_action', 'recovery'), True),
    ('Device', 'Reboot to Fastboot (Bootloader)', ('_power_action', 'bootloader'), True),
    ('Device', 'Shut Down', ('_power_action', 'shutdown'), True),
    ('Device', 'Reboot from Fastboot to Android', ('_fastboot_reboot',), True),

    # Mirroring & capture
    ('Mirror', 'Start / Stop Mirroring', ('_toggle_mirroring',), True),
    ('Mirror', 'Take Screenshot', ('_take_screenshot',), True),
    ('Mirror', 'Record Screen...', ('_record_screen',), False),
    ('Mirror', 'Wireless Mirror...', ('_wireless_mirror',), False),
    ('Mirror', 'Connect Wirelessly...', ('_show_connect_wireless_dialog',), False),
    ('Mirror', 'Screenshot Gallery...', ('_show_screenshot_gallery',), False),

    # Recovery
    ('Flash', 'Flash Recovery Image...', ('_flash_recovery_image',), False),
    ('Flash', 'Apply Update From File...', ('_apply_update_from_file',), False),

    # Backups & reports
    ('File & report', 'Backup to archive...', ('_backup_to_archive',), False),
    ('File & report', 'Restore from backup...', ('_restore_from_backup',), False),
    ('File & report', 'Generate LLM Report', ('_generate_llm_report',), True),
    ('File & report', 'Collect Bug Report...', ('_collect_bugreport',), False),

    # Tools dialogs
    ('Tools', 'Port Forwarding...', ('_show_forward_dialog',), False),
]

RECORDABLE_ACTIONS = [entry for entry in ACTIONS if entry[3]]


def action_key(entry):
    """Stable string key for one entry (method + args), used in macros."""
    method_name, args = entry[2][0], entry[2][1:]
    return ':'.join([method_name, *args])


def entry_for_key(key: str):
    """The ACTIONS entry a saved step key belongs to, or None."""
    return next((entry for entry in ACTIONS if action_key(entry) == key), None)


# Profile/macro steps the executor implements itself instead of calling a
# MainWindow action: profiles need "connect wireless to this address" and
# "start mirroring (only if not already running)", while the plain toggle
# action would happily stop a running mirror.
SPECIAL_STEP_KEYS = ('connect_wireless', 'start_mirroring')
