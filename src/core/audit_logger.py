"""Audit logger for recording user operations and destructive actions."""

import datetime
from pathlib import Path


class AuditLogger:
    _log_file = Path.home() / '.droidmgr' / 'audit.log'

    @classmethod
    def log(cls, device_id: str, operation: str, details: str = "") -> None:
        """Write an audit entry to ~/.droidmgr/audit.log."""
        try:
            cls._log_file.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = f"[{timestamp}] [DEVICE: {device_id or 'GLOBAL'}] {operation}"
            if details:
                entry += f" - {details}"
            entry += "\n"
            with open(cls._log_file, 'a', encoding='utf-8') as f:
                f.write(entry)
        except Exception:
            pass
