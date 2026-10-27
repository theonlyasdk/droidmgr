"""Per-table export for the Network tab: one table's captured rows to CSV or JSON.

Unlike the full diagnostic report (network_diag.py), this writes only the rows
of a single _SortableTree table, entirely from memory: whatever the device last
reported, with no new adb query.
"""

import csv
import json
import time
from tkinter import filedialog, messagebox

# Table attribute name on NetworkInspector -> slug for suggested filenames.
TABLE_SLUGS = {
    'traffic_table': 'data_usage',
    'socket_table': 'connections',
    'routes_table': 'routes',
    'history_table': 'history',
    'request_table': 'requests',
    'ping_table': 'ping',
}


def export_rows_to(parent, table, slug='rows'):
    """Ask where to save one table's captured rows; return the path or None.

    The format follows the chosen file extension: a '*.json' name becomes a
    JSON list of row dicts, anything else CSV. An empty table writes nothing;
    a write failure shows an error dialog here, otherwise the caller reports
    the saved path.
    """
    rows = list(getattr(table, 'raw_rows', None) or [])
    if getattr(table, 'total', 0) == 0 or not rows:
        messagebox.showinfo(
            'Export Rows',
            'Nothing captured in this table yet.\nRefresh the tab, then export.',
            parent=parent)
        return None

    filename = filedialog.asksaveasfilename(
        parent=parent,
        title='Export Table Rows',
        initialfile=f'network_{slug}_{time.strftime("%Y%m%d-%H%M%S")}',
        defaultextension='.csv',
        filetypes=[('CSV files', '*.csv'), ('JSON files', '*.json'),
                   ('All files', '*.*')])
    if not filename:
        return None

    try:
        if filename.lower().endswith('.json'):
            _write_json_rows(filename, rows)
        else:
            _write_csv_rows(filename, rows)
    except Exception as exc:
        messagebox.showerror(
            'Export Rows', f'Could not write the file:\n{exc}', parent=parent)
        return None
    return filename


def _write_csv_rows(filename, rows):
    """CSV: the first row supplies the columns; rows keep capture order."""
    columns = list(rows[0].keys())
    with open(filename, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _write_json_rows(filename, rows):
    """JSON: a list of the raw row dicts."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=2, ensure_ascii=False, default=str)
