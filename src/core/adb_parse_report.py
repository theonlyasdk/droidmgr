"""Parsing helpers for bugreport archives and dumpstate logs."""

import json
import re
import zipfile
from typing import Dict, Any, List
from .adb_parse_health import _decode_array


_BUGREPORT_HEADER_FIELDS = {
    'build': 'Build',
    'fingerprint': 'Build fingerprint',
    'bootloader': 'Bootloader',
    'radio': 'Radio',
    'network': 'Network',
    'kernel': 'Kernel',
    'uptime': 'Uptime',
    'format': 'Bugreport format version',
}


_DUMPSTATE_PROBLEM_MARKERS = (
    'Failed to find', 'No such file or directory', 'failed', 'Permission denied')


_BUGREPORT_HEADER_BYTES = 8192


_DUMPSTATE_LOG_BYTES = 65536



def _parse_bugreport_header(text: str) -> Dict[str, str]:
    """Pull the opening 'Key: value' lines out of a bugreport's header."""
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(':')
        if not separator:
            continue
        label = key.strip()
        for name, wanted in _BUGREPORT_HEADER_FIELDS.items():
            if label == wanted and name not in fields:
                fields[name] = value.strip().strip("'")
        if len(fields) == len(_BUGREPORT_HEADER_FIELDS):
            break
    return fields

def _parse_dumpstate_log(text: str) -> List[str]:
    """The lines where dumpstate records what it could not collect."""
    notes: List[str] = []
    for line in text.splitlines():
        note = line.strip()
        if not note or note in notes:
            continue
        if any(marker in note for marker in _DUMPSTATE_PROBLEM_MARKERS):
            notes.append(note)
        if len(notes) >= 6:
            break
    return notes

def _summarise_bugreport_archive(path: str) -> Dict[str, Any]:
    """Describe what a bugreport zip holds, without unpacking it.

    The entry list is read from the central directory and only a few kilobytes
    of two small text members are decompressed, so this stays cheap on a report
    that unpacks to tens of megabytes. Anything unreadable leaves the briefing
    short rather than failing a collection that already succeeded.
    """
    summary: Dict[str, Any] = {
        'entries': 0,
        'uncompressed': 0,
        'sections': [],
        'main_report': '',
        'header': {},
        'tombstones': 0,
        'anr_traces': 0,
        'largest': [],
        'collection_notes': [],
    }

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename.replace('\\', '/') for info in infos]
            summary['entries'] = len(infos)
            summary['uncompressed'] = sum(info.file_size for info in infos)

            counts: Dict[str, int] = {}
            for name in names:
                section = name.split('/')[0] + ('/' if '/' in name else '')
                counts[section] = counts.get(section, 0) + 1
            summary['sections'] = sorted(counts.items(), key=lambda item: -item[1])

            for name in names:
                lowered = name.lower()
                if 'tombstone' in lowered:
                    summary['tombstones'] += 1
                if '/anr/' in lowered or lowered.endswith('traces.txt'):
                    summary['anr_traces'] += 1
                base = name.rsplit('/', 1)[-1]
                if base.startswith('bugreport-') and base.endswith('.txt'):
                    summary['main_report'] = name

            ranked = sorted(zip(names, infos), key=lambda pair: -pair[1].file_size)
            summary['largest'] = [(name, info.file_size) for name, info in ranked[:5]]

            if summary['main_report']:
                with archive.open(summary['main_report']) as handle:
                    head = handle.read(_BUGREPORT_HEADER_BYTES)
                summary['header'] = _parse_bugreport_header(
                    head.decode('utf-8', 'replace'))

            if 'dumpstate_log.txt' in names:
                with archive.open('dumpstate_log.txt') as handle:
                    log = handle.read(_DUMPSTATE_LOG_BYTES)
                summary['collection_notes'] = _parse_dumpstate_log(
                    log.decode('utf-8', 'replace'))
    except Exception:
        pass

    return summary
