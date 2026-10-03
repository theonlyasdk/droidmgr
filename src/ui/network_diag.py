"""Ping diagnostics and report export for the network inspector."""

import json
import re
import threading
import time
from tkinter import messagebox, filedialog

from .network_format import _format_ms, _format_bytes, sanitize_network_data


class NetworkDiagMixin:
    """Ping and export methods for NetworkInspector."""


    # --- latency & ping ----------------------------------------------------

    def run_ping_on_entry(self):
        host = self.ping_host_var.get().strip()
        if not host:
            self.ping_status.config(text='Enter a host first', foreground='#C62828')
            return
        self._run_pings([(host, host)])

    def run_ping_suite(self):
        targets = []
        if self._gateway and self._gateway != 'None':
            targets.append((self._gateway, f'Gateway {self._gateway}'))
        targets.append(('8.8.8.8', 'Google DNS 8.8.8.8'))
        targets.append(('1.1.1.1', 'Cloudflare 1.1.1.1'))
        targets.append(('google.com', 'Name lookup google.com'))
        self._run_pings(targets)

    def _run_pings(self, targets):
        if self._ping_busy or not self.device_id:
            return
        self._ping_busy = True
        self.ping_table.clear()
        self.ping_status.config(text='Testing...')
        self._set_ping_controls('disabled')

        count = self.ping_count_var.get()
        device_id = self.device_id
        manager = self.device_manager

        def task():
            results = []
            for host, label in targets:
                try:
                    result = manager.ping_host(device_id, host, count)
                except Exception as exc:
                    result = {'host': host, 'error': str(exc)}
                result['label'] = label
                results.append(result)
            if self._is_alive():
                self.after(0, lambda: self._apply_pings(results))

        threading.Thread(target=task, daemon=True).start()

    def _apply_pings(self, results):
        self._ping_busy = False
        self._set_ping_controls('normal')
        self._cached_pings = results
        self.ping_table.fill(results, self._format_ping_row)

        answered = sum(1 for r in results if not r.get('error'))
        self.ping_status.config(
            text=f'{answered} of {len(results)} answered',
            foreground='gray' if answered == len(results) else '#E65100')

    @staticmethod
    def _format_ping_row(result):
        if result.get('error'):
            return (result.get('label') or result.get('host', ''), '-', '-', '-',
                    '-', '-', result['error'])

        loss = result.get('loss')
        times = result.get('times') or []
        note = ' / '.join(f"{v:.0f}" for v in times) + ' ms' if times else 'no replies'
        return (
            result.get('label') or result.get('host', ''),
            f"{loss:.0f}%" if loss is not None else '-',
            _format_ms(result.get('min')),
            _format_ms(result.get('avg')),
            _format_ms(result.get('max')),
            _format_ms(result.get('jitter')),
            note,
        )

    def _set_ping_controls(self, state):
        self.ping_button.config(state=state)
        self.ping_quick_button.config(state=state)

    # --- export -------------------------------------------------------------

    def export_report(self):
        """Export a comprehensive network diagnostic report."""
        if not self.device_id:
            messagebox.showwarning("Export Report", "No device selected.")
            return

        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export Network Diagnostic Report",
            defaultextension=".json",
            filetypes=[("JSON File", "*.json"), ("Text File", "*.txt"), ("All Files", "*.*")]
        )
        if not filename:
            return

        hide_sensitive = self.hide_sensitive_var.get()
        current_ssid = (self._cached_info.get('wifi') or {}).get('ssid') or ''

        # Prepare payload
        report_data = {
            'device_id': self.device_id,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'sensitive_masked': hide_sensitive,
            'wifi': {k: var.get() for k, var in self.wifi_vars.items()},
            'cellular': {k: var.get() for k, var in self.cell_vars.items()},
            'ip_and_routing': {k: var.get() for k, var in self.ip_vars.items()},
            'app_traffic': self._cached_traffic,
            'active_connections': self._cached_sockets,
            'routing_table': self._cached_routes,
            'connectivity_history': self._cached_history,
            'network_requests': self._cached_requests,
            'latency_diagnostics': self._cached_pings,
        }

        if hide_sensitive:
            report_data = sanitize_network_data(report_data, ssid=current_ssid)
            # Mask device serial/id if sensitive
            report_data['device_id'] = re.sub(r'[A-Za-z0-9]', 'X', self.device_id)

        try:
            if filename.lower().endswith('.txt'):
                self._write_text_report(filename, report_data)
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)

            if self.set_status:
                self.set_status(f"Exported network report to {filename}")
            messagebox.showinfo("Export Successful", f"Network diagnostic report exported to:\n{filename}")
        except Exception as exc:
            messagebox.showerror("Export Error", f"Failed to export report:\n{exc}")

    def _write_text_report(self, filename, data):
        """Format the report as human-readable text."""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"NETWORK DIAGNOSTIC REPORT\n{'=' * 70}\n")
            f.write(f"Device: {data['device_id']}\n")
            f.write(f"Generated: {data['timestamp']}\n")
            f.write(f"Sensitive Identifiers Masked: {'Yes' if data['sensitive_masked'] else 'No'}\n\n")

            f.write("1. WI-FI STATUS\n" + "-" * 70 + "\n")
            for k, v in data['wifi'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write("2. CELLULAR STATUS\n" + "-" * 70 + "\n")
            for k, v in data['cellular'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write("3. IP & ROUTING SUMMARY\n" + "-" * 70 + "\n")
            for k, v in data['ip_and_routing'].items():
                f.write(f"  {k.replace('_', ' ').capitalize():<16}: {v}\n")
            f.write("\n")

            f.write(f"4. ROUTING TABLE ({len(data['routing_table'])} routes)\n" + "-" * 70 + "\n")
            f.write(f"{'Destination':<24} {'Gateway':<16} {'Iface':<10} {'Table':<8} {'Metric':<8} {'Source':<16}\n")
            for r in data['routing_table']:
                f.write(f"{str(r.get('destination') or '-'):<24} "
                        f"{str(r.get('gateway') or '-'):<16} "
                        f"{str(r.get('interface') or '-'):<10} "
                        f"{str(r.get('table') or '-'):<8} "
                        f"{str(r.get('metric') or '-'):<8} "
                        f"{str(r.get('source') or '-'):<16}\n")
            f.write("\n")

            f.write(f"5. DATA USAGE PER APP ({len(data['app_traffic'])} apps)\n" + "-" * 70 + "\n")
            f.write(f"{'App':<34} {'Received':<12} {'Sent':<12} {'Total':<12} {'UID':<8}\n")
            for row in data['app_traffic']:
                pkg = row.get('package') or f"uid {row.get('uid')}"
                f.write(f"{pkg[:32]:<34} "
                        f"{_format_bytes(row.get('rx_bytes', 0)):<12} "
                        f"{_format_bytes(row.get('tx_bytes', 0)):<12} "
                        f"{_format_bytes(row.get('total_bytes', 0)):<12} "
                        f"{str(row.get('uid', '')):<8}\n")
            f.write("\n")

            f.write(f"6. ACTIVE CONNECTIONS ({len(data['active_connections'])} sockets)\n" + "-" * 70 + "\n")
            f.write(f"{'Direction':<12} {'Proto':<6} {'State':<12} {'Local':<22} {'Remote':<24} {'App':<20}\n")
            for s in data['active_connections']:
                loc = f"{s.get('local')}:{s.get('local_port')}"
                rem = f"{s.get('remote')}:{s.get('remote_port')}" if str(s.get('remote_port', '0')) != '0' else s.get('remote', '-')
                pkg = s.get('package') or f"uid {s.get('uid')}"
                f.write(f"{str(s.get('direction', '')):<12} "
                        f"{str(s.get('protocol', '')):<6} "
                        f"{str(s.get('state', '')):<12} "
                        f"{loc[:20]:<22} "
                        f"{rem[:22]:<24} "
                        f"{pkg[:18]:<20}\n")
            f.write("\n")

            f.write(f"7. CONNECTIVITY HISTORY ({len(data['connectivity_history'])} events)\n" + "-" * 70 + "\n")
            for h in data['connectivity_history']:
                f.write(f"[{h.get('timestamp')}] {h.get('type')}: {h.get('details')}\n")
            f.write("\n")

            if data['latency_diagnostics']:
                f.write("8. LATENCY DIAGNOSTICS\n" + "-" * 70 + "\n")
                f.write(f"{'Host':<20} {'Loss':<8} {'Min':<10} {'Avg':<10} {'Max':<10} {'Result':<20}\n")
                for p in data['latency_diagnostics']:
                    loss = f"{p.get('loss', 0):.0f}%" if p.get('loss') is not None else '-'
                    note = p.get('error') or (' / '.join(f"{v:.0f}" for v in p.get('times', [])) + ' ms' if p.get('times') else 'no replies')
                    f.write(f"{str(p.get('label') or p.get('host', '')):<20} "
                            f"{loss:<8} "
                            f"{_format_ms(p.get('min')):<10} "
                            f"{_format_ms(p.get('avg')):<10} "
                            f"{_format_ms(p.get('max')):<10} "
                            f"{note:<20}\n")
                f.write("\n")
