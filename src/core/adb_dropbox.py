"""ADBManager mixin: DropBox entries (crash, ANR and other device logs)."""

import re
from typing import Dict, List, Optional

#Parsed entries are capped so a busy DropBox cannot build a huge in-memory
# list; when more exist, the newest ones up to this count win.
_DROPBOX_MAX_ENTRIES = 400

# The most of one entry's text that is collected. Entries larger than this
# are kept as their head plus a truncation note; 'size' still counts all of
# the blob the device reported.
_DROPBOX_ENTRY_BYTE_CAP = 300 * 1024

# dumpsys opens every entry with a '***' banner line.
_HEADER_PREFIX = '***'


class _DropboxMixin:
    """_DropboxMixin for ADBManager (see adb_manager.py)."""

    def dropbox_entries(self, device_id: str) -> List[Dict[str, object]]:
        """Read the DropBox entries a device still keeps, oldest first.

        Every entry becomes a {'tag', 'time', 'size', 'data'} dict: the
        DropBox tag, the epoch-milliseconds timestamp (None when the device
        reported none), the byte size of the data blob, and the blob text
        itself. The query can take seconds on a busy device; run it from a
        worker thread.
        """
        output = self._run_command(
            ['shell', 'dumpsys', 'dropbox', '--print'], device_id, timeout=60)
        return _parse_dropbox_entries(output)


def _parse_dropbox_entries(output: str) -> List[Dict[str, object]]:
    """Chew `dumpsys dropbox --print` text into entry dicts.

    An entry runs from its '***' banner to the next banner, so blank lines
    inside a stack trace never split it. The list is newest-last (the order
    dumpsys prints in; sorted by timeMillis whenever every entry carries
    one) and trimmed to _DROPBOX_MAX_ENTRIES. Malformed chunks are ignored
    silently.
    """
    lines = output.splitlines()
    starts = [index for index, line in enumerate(lines)
              if line.startswith(_HEADER_PREFIX)]

    entries: List[Dict[str, object]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        entry = _parse_entry_chunk(lines[start + 1:end], lines[start])
        if entry is not None:
            entries.append(entry)

    if entries and all(entry['time'] is not None for entry in entries):
        entries.sort(key=lambda entry: entry['time'])
    if len(entries) > _DROPBOX_MAX_ENTRIES:
        entries = entries[-_DROPBOX_MAX_ENTRIES:]
    return entries


def _parse_entry_chunk(chunk: List[str], header: str) -> Optional[Dict[str, object]]:
    """One entry from the lines after its '***' banner, or None.

    Header: tag and timeMillis field lines followed by a data field whose
    value may carry on for any number of lines. Real builds vary a little;
    this reads the field lines the dump writes and, as a fallback, takes a
    tag-looking parenthesised token (containing '_') from the banner itself.
    """
    tag = ''
    time_ms: Optional[int] = None
    kept: List[str] = []
    total_bytes = 0
    in_data = False

    for line in chunk:
        if in_data:
            # Count every byte of the blob, but stop storing past the cap.
            total_bytes += len(line.encode('utf-8', 'replace')) + 1
            if total_bytes <= _DROPBOX_ENTRY_BYTE_CAP:
                kept.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith('tag:') and not tag:
            tag = stripped[len('tag:'):].strip()
        elif stripped.startswith('timeMillis:') and time_ms is None:
            try:
                time_ms = int(stripped[len('timeMillis:'):].strip())
            except ValueError:
                pass
        elif stripped.startswith('data:'):
            in_data = True
            remainder = stripped[len('data:'):]
            if remainder.startswith(' '):
                remainder = remainder[1:]
            if remainder:
                kept.append(remainder)
                total_bytes += len(remainder) + 1

    if not tag and header:
        for candidate in re.findall(r'\(([^()\s]+)\)', header):
            if '_' in candidate:
                tag = candidate

    if not tag or not in_data:
        return None

    # Blank lines right before the next banner separate entries; they are
    # not part of the data blob.
    while kept and kept[-1] == '':
        kept.pop()
        total_bytes -= 1

    if total_bytes > _DROPBOX_ENTRY_BYTE_CAP:
        kept.append(f"... (entry text truncated; the full blob is {total_bytes} bytes)")
    return {'tag': tag, 'time': time_ms, 'size': total_bytes,
            'data': '\n'.join(kept)}
