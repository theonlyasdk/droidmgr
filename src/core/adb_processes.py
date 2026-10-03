"""ADBManager mixin: process listing and system stats."""

import re
from typing import Dict, Any, List, Optional
from .audit_logger import AuditLogger
from .adb_parse_proc import (_top_columns, _percentage_columns, _field_at,
    _guess_res_column, _guess_args_column, _TOP_CPU_TIME,
    _parse_top_cpu_totals, _parse_top_memory_totals)


class _ProcessesMixin:
    """_ProcessesMixin for ADBManager (see adb_manager.py)."""

    def get_running_processes(self, device_id: str) -> List[Dict[str, Any]]:
        try:
            output = self._run_command(['shell', 'top', '-n', '1', '-b'], device_id)
            return self._parse_top_output(output)
        except:
            try:
                output = self._run_command(['shell', 'ps', '-eo', 'pid,user,pcpu,vsz,args'], device_id)
                return self._parse_ps_extended(output)
            except:
                output = self._run_command(['shell', 'ps', '-A'], device_id)
                return self._parse_basic_processes(output)

    def sample_process_load(self, device_id: str, timeout: int = 20) -> Dict[str, Any]:
        """One 'top' run read as a sample: the process table and the device totals.

        Both halves come out of a single command, so a sample costs one round
        trip and the totals describe the same instant as the processes listed
        under them. Two 'top' runs a moment apart never agree exactly, so reading
        the table and the totals separately would show that disagreement as
        real movement in a graph.
        """
        output = self._run_command(['shell', 'top', '-n', '1', '-b'],
                                   device_id, timeout=timeout)
        return {
            'processes': self._parse_top_output(output),
            'cpu': _parse_top_cpu_totals(output),
            'memory': _parse_top_memory_totals(output),
        }

    def _parse_top_output(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        header_found = False
        columns: Dict[str, int] = {}
        
        for line in lines:
            if 'PID' in line.upper():
                header_found = True
                columns = _top_columns(line)
                continue
            
            if header_found and line.strip():
                parts = line.split()
                if len(parts) < 5 or not parts[0].isdigit() or parts[0] == '0':
                    continue
                
                try:
                    # Positions come from the header rather than from a search
                    # for a '%' in the row. toybox writes the values as bare
                    # numbers and keeps the '%' in the label above them, so a
                    # row-wide search finds nothing at all and every CPU figure
                    # comes back as zero.
                    cpu_index = columns.get('cpu')
                    mem_index = columns.get('mem')
                    if cpu_index is None or mem_index is None:
                        # A header that names no such column still gets the
                        # older guess, in case that build marks the values
                        # themselves with a '%'.
                        found_cpu, found_mem = _percentage_columns(parts)
                        if cpu_index is None:
                            cpu_index = found_cpu
                        if mem_index is None:
                            mem_index = found_mem
                    
                    cpu = _field_at(parts, cpu_index).rstrip('%') or '0'
                    mem = _field_at(parts, mem_index) or _guess_res_column(parts)
                    
                    # A header that does not match its own rows puts the name in
                    # the wrong place, and the CPU time is what it lands on, so
                    # that reading is thrown away rather than shown as a command.
                    name = _field_at(parts, columns.get('name'))
                    if _TOP_CPU_TIME.match(name):
                        name = ''
                    name = name or _guess_args_column(parts)
                    
                    process = {
                        'pid': parts[0],
                        'user': parts[1] if len(parts) > 1 else 'sys',
                        'cpu': cpu,
                        'mem': self._format_memory(mem),
                        'name': name
                    }
                    processes.append(process)
                except Exception:
                    continue
        
        if processes:
            return sorted(processes, key=lambda x: float(x.get('cpu', 0) or 0), reverse=True)[:50]
        
        return self._parse_basic_processes(output)

    def _parse_ps_extended(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split(None, 4)
            if len(parts) >= 5:
                cmd_parts = parts[4].split()
                name = cmd_parts[0] if cmd_parts else 'unknown'
                process = {
                    'pid': parts[0],
                    'user': parts[1],
                    'cpu': parts[2],
                    'mem': self._format_memory(parts[3]),
                    'name': name
                }
                processes.append(process)

        
        return processes[:50]

    def _parse_basic_processes(self, output: str) -> List[Dict[str, Any]]:
        processes = []
        lines = output.split('\n')
        
        for line in lines[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 9:
                process = {
                    'pid': parts[1],
                    'user': parts[0],
                    'cpu': '0',
                    'mem': '0',
                    'name': parts[-1]
                }
                processes.append(process)
        
        return processes[:50]

    def _format_memory(self, mem_str: str) -> str:
        if not mem_str or mem_str == '0':
            return '0 KB'
        
        mem_str = mem_str.strip()
        
        if '%' in mem_str:
            return mem_str
        
        # Handle cases where it already has a suffix
        if 'G' in mem_str or 'M' in mem_str or 'K' in mem_str:
            return mem_str.replace('G', ' GB').replace('M', ' MB').replace('K', ' KB')
        
        try:
            mem_kb = int(mem_str)
            if mem_kb < 1024:
                return f"{mem_kb} KB"
            elif mem_kb < 1024 * 1024:
                return f"{mem_kb // 1024} MB"
            else:
                return f"{mem_kb / (1024 * 1024):.1f} GB"
        except ValueError:
            return mem_str

    def _format_file_size(self, size_str: str) -> str:
        try:
            size_bytes = int(size_str)
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
        except ValueError:
            return size_str

    def get_system_stats(self, device_id: str) -> Dict[str, Any]:
        stats = {}
        
        try:
            meminfo = self._run_command(['shell', 'cat', '/proc/meminfo'], device_id)
            total_kb = 0
            avail_kb = 0
            free_kb = 0
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    total_kb = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    avail_kb = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    free_kb = int(line.split()[1])
                    
            target_avail = avail_kb if avail_kb > 0 else free_kb
            if target_avail > 0:
                stats['free_memory'] = self._format_memory(str(target_avail))
            if total_kb > 0:
                stats['total_memory'] = self._format_memory(str(total_kb))

        except:
            pass
        
        try:
            cpuinfo = self._run_command(['shell', 'cat', '/proc/cpuinfo'], device_id)
            cpu_count = cpuinfo.count('processor')
            stats['cpu_cores'] = cpu_count if cpu_count > 0 else 1
        except:
            stats['cpu_cores'] = 1
        
        return stats

    def kill_process(self, device_id: str, pid: str) -> None:
        AuditLogger.log(device_id, "KILL_PROCESS", f"PID: {pid}")
        self._run_command(['shell', 'kill', pid], device_id)

