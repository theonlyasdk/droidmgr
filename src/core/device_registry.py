"""Persistent per-device database for droidmgr.

Remembers every device ever connected (keyed by serial) along with stable
facts about it: model, Android version, root status, first/last seen.
Features that need device facts without paying for fresh adb round trips
(for example the file manager's permission-denied hint) read them here.

Perf/memory notes (checked after implementation):
- One small JSON file (~hundreds of bytes per device); loaded once, saved
  only when data actually changed, throttled to at most one write per
  minute during polling.
- record_seen() never touches adb; enrichment (getprops + root check) runs
  at most once per device per app session via claim_enrichment().
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# A reconnect within this window counts as the same session, not a new one.
SESSION_GAP_SECONDS = 10 * 60
_SAVE_THROTTLE_SECONDS = 60


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


class DeviceRegistry:
    """JSON-backed store of known devices under ~/.droidmgr/devices.json."""

    def __init__(self, db_file: Optional[str] = None):
        if db_file is None:
            db_file = str(Path.home() / '.droidmgr' / 'devices.json')
        self.db_file = db_file
        # RLock: record_* methods hold the lock while _mark_dirty -> save()
        # re-acquires it on the same thread.
        self._lock = threading.RLock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._enrichment_claimed: set = set()
        self._dirty = False
        self._last_save = 0.0
        self._load()

    # -- persistence ---------------------------------------------------

    def _load(self):
        try:
            if os.path.isfile(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                devices = data.get('devices', {})
                if isinstance(devices, dict):
                    self._devices = {str(k): v for k, v in devices.items()
                                     if isinstance(v, dict)}
        except Exception as e:
            print(f"Error loading device registry: {e}")
            self._devices = {}

    def save(self, force: bool = False):
        """Write the file if dirty (or forced); throttled during polling."""
        with self._lock:
            if not self._dirty and not force:
                return
            if not force and time.time() - self._last_save < _SAVE_THROTTLE_SECONDS:
                return
            try:
                directory = os.path.dirname(self.db_file)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                tmp = self.db_file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({'devices': self._devices}, f, indent=2)
                os.replace(tmp, self.db_file)
                self._dirty = False
                self._last_save = time.time()
            except Exception as e:
                print(f"Error saving device registry: {e}")

    def _mark_dirty(self):
        self._dirty = True
        # Opportunistic throttled write so data survives a crash; the
        # authoritative save happens on app close (save() throttles itself).
        self.save()

    # -- recording -----------------------------------------------------

    def _entry(self, serial: str) -> Dict[str, Any]:
        entry = self._devices.get(serial)
        if entry is None:
            entry = {'serial': serial}
            self._devices[serial] = entry
        return entry

    def record_seen(self, serial: str, model: Optional[str] = None,
                    status: Optional[str] = None):
        """Cheap per-poll heartbeat: no adb, only identity + timestamps."""
        if not serial:
            return
        with self._lock:
            entry = self._entry(serial)
            now = _now_iso()
            if 'first_seen' not in entry:
                entry['first_seen'] = now
                entry['sessions'] = 1
            else:
                try:
                    gap = (datetime.now() - datetime.fromisoformat(
                        entry.get('last_seen', entry['first_seen']))).total_seconds()
                except Exception:
                    gap = SESSION_GAP_SECONDS
                if gap >= SESSION_GAP_SECONDS:
                    entry['sessions'] = int(entry.get('sessions', 0)) + 1
            entry['last_seen'] = now
            if model:
                entry['model'] = model
            if status:
                entry['last_status'] = status
            self._mark_dirty()

    def claim_enrichment(self, serial: str) -> bool:
        """True once per session per device: the caller must go enrich it."""
        with self._lock:
            if serial in self._enrichment_claimed:
                return False
            self._enrichment_claimed.add(serial)
            return True

    def release_enrichment(self, serial: str):
        """Allow a later retry (e.g. enrichment failed while offline)."""
        with self._lock:
            self._enrichment_claimed.discard(serial)

    def record_details(self, serial: str, details: Dict[str, Any]):
        """Merge stable device facts (model, Android version, build, ...)."""
        if not serial or not details:
            return
        keep = ('model', 'manufacturer', 'android_version',
                'android_codename', 'build_id', 'product_name')
        with self._lock:
            entry = self._entry(serial)
            for key in keep:
                value = details.get(key)
                if value:
                    entry[key] = str(value)
            entry['details_updated_at'] = _now_iso()
            self._mark_dirty()

    def record_root(self, serial: str, root: Dict[str, Any]):
        """Merge a root check ({adb_root, shell_uid, su_path})."""
        if not serial or not root:
            return
        with self._lock:
            entry = self._entry(serial)
            adb_root = bool(root.get('adb_root'))
            su_path = str(root.get('su_path') or '')
            entry['adb_root'] = adb_root
            entry['shell_uid'] = str(root.get('shell_uid') or '')
            entry['su_path'] = su_path
            # su present means the firmware is rooted even when adb itself
            # is not root; no su at all means not rooted (or well hidden).
            entry['rooted'] = adb_root or bool(su_path)
            entry['root_checked_at'] = _now_iso()
            self._mark_dirty()

    # -- reading -------------------------------------------------------

    def get(self, serial: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._devices.get(serial, {}))

    def is_rooted(self, serial: str) -> Optional[bool]:
        """True/False when a root check was recorded, else None (unknown)."""
        with self._lock:
            entry = self._devices.get(serial)
            if not entry or 'rooted' not in entry:
                return None
            return bool(entry['rooted'])

    def is_adb_root(self, serial: str) -> Optional[bool]:
        with self._lock:
            entry = self._devices.get(serial)
            if not entry or 'adb_root' not in entry:
                return None
            return bool(entry['adb_root'])
