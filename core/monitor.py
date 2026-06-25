"""
core/monitor.py — Proactive system monitor
Watches CPU, disk, memory, failed services in background.
Calls alert_callback(message) when something needs attention.
"""
import logging
import subprocess
import threading
import time
from typing import Callable

import psutil

log = logging.getLogger('flash.monitor')


class ProactiveMonitor:
    def __init__(self, alert_callback: Callable[[str], None]):
        self.alert = alert_callback
        self._running = False
        self._thread  = None
        self._last_alerts: dict = {}   # debounce — don't repeat same alert
        self._DEBOUNCE = 300           # seconds between same alert

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Proactive monitor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._check_disk()
                self._check_ram()
                self._check_cpu()
                self._check_services()
            except Exception as e:
                log.debug(f"Monitor error: {e}")
            time.sleep(30)   # check every 30s

    def _should_alert(self, key: str) -> bool:
        now = time.time()
        last = self._last_alerts.get(key, 0)
        if now - last > self._DEBOUNCE:
            self._last_alerts[key] = now
            return True
        return False

    def _check_disk(self):
        usage = psutil.disk_usage('/')
        if usage.percent > 90 and self._should_alert('disk_90'):
            self.alert(f"Heads up — disk is {usage.percent:.0f}% full. "
                       f"Only {usage.free // 1024**3}GB left.")
        elif usage.percent > 80 and self._should_alert('disk_80'):
            self.alert(f"Disk is {usage.percent:.0f}% full, "
                       f"{usage.free // 1024**3}GB remaining.")

    def _check_ram(self):
        mem = psutil.virtual_memory()
        if mem.percent > 92 and self._should_alert('ram_92'):
            self.alert(f"RAM is critically high at {mem.percent:.0f}%. "
                       f"Only {mem.available // 1024**2}MB free.")

    def _check_cpu(self):
        cpu = psutil.cpu_percent(interval=2)
        if cpu > 95 and self._should_alert('cpu_95'):
            # Find what's eating CPU
            try:
                top = subprocess.run(
                    ['ps', 'aux', '--sort=-%cpu'],
                    capture_output=True, text=True, timeout=5
                )
                lines = top.stdout.strip().split('\n')
                culprit = lines[1].split()[10] if len(lines) > 1 else 'unknown'
                self.alert(f"CPU is maxed at {cpu:.0f}%. "
                           f"Top process: {culprit}")
            except Exception:
                self.alert(f"CPU is at {cpu:.0f}% — something is pegging it.")

    def _check_services(self):
        critical = ['ollama']   # only check flash's own dependencies
        for svc in critical:
            try:
                r = subprocess.run(
                    ['systemctl', 'is-active', svc],
                    capture_output=True, text=True, timeout=3
                )
                if r.stdout.strip() != 'active':
                    if self._should_alert(f'svc_{svc}'):
                        self.alert(f"Warning — {svc} service is not running. "
                                   f"Flash may not work correctly.")
            except Exception:
                pass
