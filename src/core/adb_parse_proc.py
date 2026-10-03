"""Pure parsing helpers for top/ps process output."""

import re
from typing import Dict, Any, List, Optional, Tuple
# reading after it one place earlier than the count of labels suggests.
_TOP_COLUMN_NAMES = {
    'PID': 'pid', 'USER': 'user', 'CPU': 'cpu', '%CPU': 'cpu', 'RES': 'mem',
    'MEM': 'mem', '%MEM': 'mem_percent', 'ARGS': 'name', 'CMDLINE': 'name',
    'CPULINE': 'name', 'NAME': 'name',
}

_TOP_CPU_TIME = re.compile(r'^\d+:\d{2}([.:]\d+)?$')

# task manager shows, while the per-process figures are each per single core.
_TOP_CPU_TOTALS = re.compile(
    r'([\d.]+)%\s*cpu\s+([\d.]+)%\s*user\s+([\d.]+)%\s*nice\s+'
    r'([\d.]+)%\s*sys\s+([\d.]+)%\s*idle')
_TOP_MEMORY_TOTALS = re.compile(
    r'Mem:\s+([\d.]+\s*[KMGT])\s+total,\s+([\d.]+\s*[KMGT])\s+used,'
    r'\s+([\d.]+\s*[KMGT])\s+free')
_SIZE_UNITS = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}

def _top_columns(header: str) -> Dict[str, int]:
    """Map each 'top' column label to the position its value sits at in a row."""
    labels: List[str] = []
    for token in header.split():
        left, bracket, right = token.partition('[')
        if bracket and right.endswith(']'):
            labels.extend(part for part in (left, right[:-1]) if part)
        else:
            labels.append(token)

    columns: Dict[str, int] = {}
    for index, label in enumerate(labels):
        key = _TOP_COLUMN_NAMES.get(label.upper())
        if key and key not in columns:
            columns[key] = index
    return columns

def _field_at(parts: List[str], index: Optional[int]) -> str:
    """One field out of a row, by the position its header label was found at."""
    if index is None or index >= len(parts):
        return ''
    return parts[index]

def _percentage_columns(parts: List[str]) -> Tuple[Optional[int], Optional[int]]:
    """Where the CPU and memory percentages sit, judged by the '%' they carry.

    This is the older guess, kept for a header that names no column to read: a
    build labelling its columns differently may still write the '%' into the
    values themselves, which is what this looks for.
    """
    cpu_index = None
    mem_index = None
    for index, part in enumerate(parts):
        if '%' not in part:
            continue
        if cpu_index is None:
            cpu_index = index
        elif mem_index is None:
            mem_index = index
    return cpu_index, mem_index

def _guess_res_column(parts: List[str]) -> str:
    """The resident size, for when the header names no column to read.

    'top' prints VIRT before RES, so of the two sizes it reports the second is
    the one counted against physical memory.
    """
    candidates = [part for part in parts
                  if any(unit in part for unit in 'KMG')
                  and any(char.isdigit() for char in part)]
    if len(candidates) >= 2:
        return candidates[1]
    return candidates[0] if candidates else '0'

def _guess_args_column(parts: List[str]) -> str:
    """The command name, which is whatever follows the CPU time '0:00.30'."""
    for index, part in enumerate(parts):
        if ':' in part and index >= 5 and index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1] if parts else 'unknown'

def _process_cpu(process: Dict[str, Any]) -> float:
    """A process's CPU figure as a number, whichever way it was written."""
    try:
        return float(str(process.get('cpu', 0)).rstrip('%'))
    except (TypeError, ValueError):
        return 0.0

def _size_to_bytes(text: str) -> int:
    """'3.6G' as the byte count it stands for."""
    text = (text or '').strip()
    if not text:
        return 0
    scale = _SIZE_UNITS.get(text[-1].upper(), 1)
    if scale != 1:
        text = text[:-1]
    try:
        return int(float(text) * scale)
    except ValueError:
        return 0

def _parse_top_cpu_totals(output: str) -> Dict[str, float]:
    """The device's CPU summary, read out of a 'top' run."""
    for line in output.splitlines():
        match = _TOP_CPU_TOTALS.search(line)
        if not match:
            continue
        total = float(match.group(1))
        idle = float(match.group(5))
        busy = 0.0
        if total > 0:
            busy = max(0.0, min(100.0, (total - idle) * 100.0 / total))
        return {
            'cores': total / 100.0,
            'user': float(match.group(2)),
            'nice': float(match.group(3)),
            'system': float(match.group(4)),
            'idle': idle,
            'busy': round(busy, 1),
        }
    return {}

def _parse_top_memory_totals(output: str) -> Dict[str, int]:
    """The device's memory summary, read out of a 'top' run, in bytes."""
    for line in output.splitlines():
        match = _TOP_MEMORY_TOTALS.search(line)
        if not match:
            continue
        return {
            'total_bytes': _size_to_bytes(match.group(1)),
            'used_bytes': _size_to_bytes(match.group(2)),
            'free_bytes': _size_to_bytes(match.group(3)),
        }
    return {}

