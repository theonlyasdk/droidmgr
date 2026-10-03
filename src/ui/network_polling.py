"""Device lifecycle and polling loop for the network inspector."""

import threading
import tkinter as tk


class NetworkPollingMixin:
    """Lifecycle and polling methods for NetworkInspector."""


    def set_device(self, device_id):
        """Set the active device and reload data."""
        if self.device_id == device_id and self.loaded:
            self.start_polling()
            return
        self.stop_polling()
        self.device_id = device_id
        self.loaded = False
        self._cached_info = {}
        self._cached_traffic = []
        self._cached_sockets = []
        self._cached_routes = []
        self._cached_history = []
        self._cached_requests = []
        self._cached_pings = []

        if device_id:
            self.load()
        else:
            self._clear_all()

    def _clear_all(self):
        self.stop_polling()
        for var in self.wifi_vars.values():
            var.set('-')
        for var in self.cell_vars.values():
            var.set('-')
        for var in self.ip_vars.values():
            var.set('-')
        self.connection_notice.config(text='')
        self.status_label.config(text='')
        self.traffic_table.clear()
        self.socket_table.clear()
        self.routes_table.clear()
        self.history_table.clear()
        self.request_table.clear()
        self.ping_table.clear()
        self.traffic_summary.config(text='')
        self.socket_summary.config(text='')
        self.routes_summary.config(text='')
        self.history_summary.config(text='')
        self.request_summary.config(text='')
        self.ping_status.config(text='')

    def load(self):
        """Load all network inspection data once and start polling."""
        if not self.device_id or not self.device_manager:
            return
        self.refresh_connection()
        self.refresh_traffic()
        self.refresh_connections()
        self.refresh_routes()
        self.refresh_history()
        self.refresh_requests()
        self.loaded = True
        self.start_polling()

    def refresh_all(self):
        """Refresh all network data."""
        if not self.device_id:
            if self.show_error:
                self.show_error("No device selected.")
            return
        self.refresh_connection()
        self.refresh_traffic()
        self.refresh_connections()
        self.refresh_routes()
        self.refresh_history()
        self.refresh_requests()

    def get_polling_interval_ms(self):
        """Read query interval from settings (in milliseconds)."""
        if self.config:
            try:
                sec = self.config.get('general', 'query_interval', 5)
                return max(1, int(sec)) * 1000
            except Exception:
                pass
        return 5000

    def start_polling(self):
        """Start auto-refreshing at the interval configured in settings."""
        self.stop_polling()
        if not self._is_alive() or not self.device_id:
            return
        interval = self.get_polling_interval_ms()
        self._poll_job = self.after(interval, self._poll_tick)

    def stop_polling(self):
        """Stop periodic auto-refresh."""
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    def _poll_tick(self):
        """Periodic timer callback running at settings polling interval."""
        self._poll_job = None
        if not self._is_alive() or not self.device_id:
            return

        # Only query if the tab is visible/mapped to conserve resources
        if self.winfo_ismapped():
            # Refresh connection status (Wi-Fi, cellular, signal, link speed, IP)
            self.refresh_connection()

            # Refresh currently active subtab
            try:
                current = self.notebook.select()
                if current:
                    tab_name = self.notebook.tab(current, 'text')
                    if 'Data usage' in tab_name:
                        self.refresh_traffic()
                    elif 'Active connections' in tab_name:
                        self.refresh_connections()
                    elif 'Routes' in tab_name:
                        self.refresh_routes()
                    elif 'Connectivity history' in tab_name:
                        self.refresh_history()
                    elif 'Network requests' in tab_name:
                        self.refresh_requests()
            except Exception:
                pass

        # Reschedule next tick at current settings interval
        interval = self.get_polling_interval_ms()
        self._poll_job = self.after(interval, self._poll_tick)

    # --- threading runner ---------------------------------------------------

    def _is_alive(self):
        try:
            return self.winfo_exists()
        except tk.TclError:
            return False

    def _run(self, busy_flag, work, apply, on_error):
        """Execute on a worker thread and update UI on main thread."""
        if getattr(self, busy_flag):
            return
        setattr(self, busy_flag, True)

        def finish(callback, *args):
            setattr(self, busy_flag, False)
            callback(*args)

        def task():
            try:
                result = work()
            except Exception as exc:
                message = str(exc)
                if self._is_alive():
                    self.after(0, lambda: finish(on_error, message))
                return
            if self._is_alive():
                self.after(0, lambda: finish(apply, result))

        threading.Thread(target=task, daemon=True).start()
