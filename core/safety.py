"""
core/safety.py — Command Safety Layer
================================================================================
Classifies bash commands by risk level.
Safe commands run immediately.
Risky commands require user confirmation via UI dialog.
Blocks the most dangerous patterns entirely.
================================================================================
"""

import logging
import re
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

log = logging.getLogger('flash.safety')

# ── Patterns: ALWAYS require explicit confirmation ─────────────────────────────
DESTRUCTIVE_PATTERNS = [
    r'\brm\s+-[rf]',          # rm -rf
    r'\brm\b.*[/*]',          # rm with wildcards
    r'\bdd\b',                # disk dump (extremely dangerous)
    r'\bmkfs\b',              # format filesystem
    r'\bfdisk\b',             # partition editor
    r'\bparted\b',
    r'\bsudo\s+rm\b',
    r'\bsudo\s+dd\b',
    r'\b>\s*/dev/',           # writing to device files
    r'\bsystemctl\s+stop\b',
    r'\bsystemctl\s+disable\b',
    r'\bkillall\b',
    r'\bpkill\b',
    r'\bapt[-\s]+(remove|purge|autoremove)\b',
    r'\bdpkg\s+--purge\b',
    r'\bchmod\s+777\b',       # making things world-writable
    r'\bchown\s+root\b',
    r'curl.*\|\s*(bash|sh)',   # curl pipe to shell
    r'wget.*\|\s*(bash|sh)',
]

# ── Patterns: require confirmation (lower risk but still modifying) ────────────
REVIEW_PATTERNS = [
    r'\bsudo\b',
    r'\bapt\b',
    r'\bdpkg\b',
    r'\bpip\s+install\b',
    r'\bnpm\s+install\b',
    r'\bsystemctl\b',
    r'\bkill\s+\d+',
    r'\bmv\b.*',
    r'\bcp\s+-r\b',
    r'\bchmod\b',
    r'\bchown\b',
    r'\bcrontab\b',
    r'>\s*/etc/',             # writing to /etc
    r'>>\s*/etc/',
    r'\bgit\s+push\b',
    r'\bgit\s+reset\b',
    r'\bgit\s+force\b',
]

# ── Patterns: always safe (read-only) ─────────────────────────────────────────
SAFE_PATTERNS = [
    r'^ls(\s|$)',
    r'^cat\b',
    r'^echo\b',
    r'^pwd$',
    r'^ps\b',
    r'^df\b',
    r'^free\b',
    r'^uname\b',
    r'^whoami$',
    r'^date\b',
    r'^uptime\b',
    r'^hostname$',
    r'^which\b',
    r'^find\b.*-name\b',
    r'^grep\b',
    r'^head\b',
    r'^tail\b',
    r'^wc\b',
    r'^sort\b',
    r'^uniq\b',
    r'^cut\b',
    r'^awk\b',
    r'^sed\b',
    r'^diff\b',
    r'^journalctl\b',
    r'^systemctl\s+(status|is-active|list-units)\b',
    r'^top\b',
    r'^htop\b',
    r'^nvidia-smi\b',
    r'^git\s+(status|log|diff|show)\b',
    r'^python3?\s+-c\s+["\']?print\b',
    r'^pip\s+(list|show|freeze)\b',
    r'^ollama\s+(list|show|ps)\b',
]


class SafetyLayer:
    """
    Classifies and gates command execution.
    """

    def needs_confirmation(self, command: str) -> bool:
        """Returns True if the command should be confirmed before running."""
        cmd = command.strip()

        # Check safe list first
        for pattern in SAFE_PATTERNS:
            if re.match(pattern, cmd, re.IGNORECASE):
                return False

        # Check destructive list
        for pattern in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True

        # Check review list
        for pattern in REVIEW_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True

        # Unknown — ask anyway (safe default)
        return True

    def is_blocked(self, command: str) -> bool:
        """
        Returns True if command is too dangerous to even ask about.
        (e.g. rm -rf / — never run this no matter what)
        """
        dangerous = [
            r'rm\s+-[rf]+\s+/',           # rm -rf /
            r'rm\s+-[rf]+\s+\*',          # rm -rf *
            r'dd\s+.*of=/dev/[sh]d[a-z]', # dd to whole disk
            r'mkfs\s+/dev/[sh]d[a-z]$',  # format whole disk
            r'>\s*/dev/[sh]d[a-z]$',      # overwrite whole disk
        ]
        for pattern in dangerous:
            if re.search(pattern, command, re.IGNORECASE):
                log.critical(f"BLOCKED catastrophic command: {command}")
                return True
        return False

    def confirm_sync(self, command: str, explanation: str = "") -> bool:
        """
        Show a modal dialog to confirm command execution.
        Returns True if user approves.
        This MUST be called from the main Qt thread (or via signal).
        """
        if self.is_blocked(command):
            log.critical(f"Blocked dangerous command: {command}")
            return False

        result = [False]
        event = threading.Event()

        def _show_dialog():
            # Determine risk level for dialog styling
            risk = 'HIGH' if any(
                re.search(p, command, re.IGNORECASE)
                for p in DESTRUCTIVE_PATTERNS
            ) else 'MODERATE'

            emoji = '🔴' if risk == 'HIGH' else '⚠️'
            msg = QMessageBox()
            msg.setWindowTitle(f"Flash Copilot — {emoji} Confirm Command")
            msg.setWindowFlags(
                msg.windowFlags() |
                Qt.WindowType.WindowStaysOnTopHint
            )

            msg.setText(
                f"<b>Flash wants to run this command:</b><br><br>"
                f"<code style='background:#1a1a2e;color:#00ff88;"
                f"padding:8px;border-radius:4px;font-size:14px'>"
                f"{command}</code><br><br>"
                f"Risk level: <b style='color:"
                f"{'red' if risk == 'HIGH' else 'orange'}'>{risk}</b>"
            )
            if explanation:
                msg.setInformativeText(explanation)

            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            msg.button(QMessageBox.StandardButton.Yes).setText("Run It ✓")
            msg.button(QMessageBox.StandardButton.No).setText("Cancel ✗")

            choice = msg.exec()
            result[0] = (choice == QMessageBox.StandardButton.Yes)
            event.set()

        # Schedule on Qt main thread
        app = QApplication.instance()
        if app:
            app.callInMainThread(_show_dialog) \
                if hasattr(app, 'callInMainThread') else _show_dialog()
        else:
            _show_dialog()

        event.wait(timeout=60)  # User has 60 seconds to respond
        log.info(f"Command {'approved' if result[0] else 'rejected'}: {command}")
        return result[0]

    def get_risk_label(self, command: str) -> str:
        """Return a human-readable risk label."""
        if self.is_blocked(command):
            return 'BLOCKED'
        if any(re.search(p, command, re.IGNORECASE) for p in DESTRUCTIVE_PATTERNS):
            return 'HIGH'
        if any(re.search(p, command, re.IGNORECASE) for p in REVIEW_PATTERNS):
            return 'MODERATE'
        return 'SAFE'
