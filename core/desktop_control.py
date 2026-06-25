"""
core/desktop_control.py — Desktop Control (Final)

All desktop capabilities in one clean class.
Every method returns a string suitable for logging/history.
TTS formatting is done by brain.py, not here.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psutil

log = logging.getLogger("flash.desktop")

_CFG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def _cfg() -> dict:
    try:
        return json.loads(_CFG_PATH.read_text())
    except Exception:
        return {}


APP_ALIASES = {
    "chrome": "google-chrome",
    "chromium": "chromium-browser",
    "firefox": "firefox",
    "terminal": "gnome-terminal",
    "files": "nautilus",
    "file manager": "nautilus",
    "text editor": "gedit",
    "vscode": "code",
    "code editor": "code",
    "spotify": "spotify",
    "slack": "slack",
    "discord": "discord",
    "calculator": "gnome-calculator",
    "settings": "gnome-control-center",
    "system monitor": "gnome-system-monitor",
}

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    51: "light drizzle",
    53: "drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    80: "showers",
    81: "heavy showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
}


class DesktopControl:
    def __init__(self):
        cfg = _cfg()
        self._tz = ZoneInfo(cfg.get("user_timezone", "America/New_York"))
        self._lat = cfg.get("user_lat", 40.7128)
        self._lon = cfg.get("user_lon", -74.0060)
        self._city = cfg.get("user_city", "New York")

    # ── Commands ──────────────────────────────────────────────────────────────
    def run_command(self, command: str, timeout: int = 30) -> tuple[str, str]:
        log.info(f"run: {command}")
        try:
            r = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "TERM": "xterm"},
            )
            out = r.stdout.strip()
            err = r.stderr.strip()
            return (out[:3000] if len(out) > 3000 else out), err
        except subprocess.TimeoutExpired:
            return "", f"Timed out after {timeout}s"
        except Exception as e:
            return "", str(e)

    # ── Apps / URLs ───────────────────────────────────────────────────────────
    def open_application(self, app_name: str):
        cmd = APP_ALIASES.get(app_name.lower().strip(), app_name)
        log.info(f"open_app: {cmd}")
        try:
            subprocess.Popen(
                cmd.split(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            subprocess.Popen(
                ["xdg-open", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    def open_url(self, url: str):
        log.info(f"open_url: {url}")
        try:
            subprocess.Popen(
                ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            log.error(f"open_url failed: {e}")

    def open_url_and_type(self, url: str, query: str, delay: float = 2.5) -> str:
        """Open URL then type a query into the page."""
        log.info(f"open_url_and_type: {url} → '{query}'")
        self.open_url(url)
        time.sleep(delay)
        if not shutil.which("xdotool"):
            return f"Opened {url} — xdotool not installed for typing"
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "40", query], timeout=15
            )
            time.sleep(0.3)
            subprocess.run(["xdotool", "key", "Return"], timeout=5)
            return f"Opened and searched for: {query}"
        except Exception as e:
            return f"Opened {url} — typing failed: {e}"

    def play_youtube(self, query: str) -> str:
        """
        Search YouTube and play the first result with mpv.
        This actually plays the video — unlike open_url which just opens a page.
        """
        log.info(f"play_youtube: {query}")
        # Try yt-dlp + mpv (best approach)
        if shutil.which("yt-dlp") and shutil.which("mpv"):
            try:
                # Get first video URL
                result = subprocess.run(
                    [
                        "yt-dlp",
                        "--no-playlist",
                        "--get-url",
                        "--format",
                        "best[height<=720]",
                        f"ytsearch1:{query}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                video_url = result.stdout.strip().split("\n")[0]
                if video_url and video_url.startswith("http"):
                    subprocess.Popen(
                        ["mpv", "--really-quiet", video_url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return f"Playing: {query}"
            except Exception as e:
                log.warning(f"yt-dlp/mpv failed: {e}")

        # Fallback: open YouTube search in browser
        q = query.replace(" ", "+")
        self.open_url(f"https://www.youtube.com/results?search_query={q}")
        return f"Opened YouTube search for {query}. " f"Say 'click play' to start the first video."

    # ── Keyboard / input ──────────────────────────────────────────────────────
    def keyboard_shortcut(self, keys: str) -> str:
        """Press a keyboard shortcut using xdotool."""
        if not shutil.which("xdotool"):
            return "xdotool not installed — run: sudo apt install xdotool"
        try:
            # Convert human shortcut to xdotool format
            # ctrl+w → ctrl+w, alt+f4 → alt+F4
            xkeys = keys.lower().strip()
            subprocess.run(["xdotool", "key", xkeys], timeout=5, capture_output=True)
            return f"Pressed {keys}"
        except Exception as e:
            return f"Could not press {keys}: {e}"

    def type_text(self, text: str):
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "type", "--clearmodifiers", text], timeout=10)
        else:
            log.error("xdotool not installed")

    def click_play(self) -> str:
        """Click the first video on a YouTube results page."""
        if not shutil.which("xdotool"):
            return "xdotool not installed — run: sudo apt install xdotool"
        try:
            time.sleep(1.0)
            # Focus browser, press Tab to select first video, Enter to play
            subprocess.run(["xdotool", "key", "Tab"], timeout=3, capture_output=True)
            time.sleep(0.2)
            subprocess.run(["xdotool", "key", "Tab"], timeout=3, capture_output=True)
            time.sleep(0.2)
            subprocess.run(["xdotool", "key", "Return"], timeout=3, capture_output=True)
            return "Clicked play on first video."
        except Exception as e:
            return f"Click play failed: {e}"

    def get_active_window(self) -> str:
        if shutil.which("xdotool"):
            try:
                r = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                return r.stdout.strip()
            except Exception:
                pass
        return "unknown"

    # ── VS Code ───────────────────────────────────────────────────────────────
    def vscode_file(self) -> str:
        """Get and read the currently open file in VS Code."""
        window = self.get_active_window()
        log.info(f"Active window: {window}")

        # VS Code title: "filename — folder — Visual Studio Code"
        if "Visual Studio Code" in window or "code" in window.lower():
            # Extract filename from title
            parts = window.split("—")
            if parts:
                filename = parts[0].strip().lstrip("●").strip()
                if filename and filename not in ("Welcome", "Get Started", "Untitled"):
                    # Search for file
                    for search_dir in [
                        os.path.expanduser("~/Downloads"),
                        os.path.expanduser("~/Documents"),
                        os.path.expanduser("~/Desktop"),
                        os.path.expanduser("~"),
                    ]:
                        try:
                            r = subprocess.run(
                                [
                                    "find",
                                    search_dir,
                                    "-name",
                                    filename,
                                    "-maxdepth",
                                    "6",
                                    "-not",
                                    "-path",
                                    "*/.*",
                                ],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            found = [line for line in r.stdout.strip().split("\n") if line]
                            if found:
                                path = found[0]
                                content = self.read_file(path)
                                return f"Open file: {path}\n\n{content}"
                        except Exception:
                            continue
                    return f"VS Code has '{filename}' open but couldn't find the file path."
            return f"VS Code is open. Window: {window}"
        return f"VS Code doesn't seem to be focused. Active window: {window}"

    # ── Screen / OCR ─────────────────────────────────────────────────────────
    def read_screen(self) -> str:
        """Screenshot + tesseract OCR. Returns extracted text."""
        if not shutil.which("tesseract"):
            return "tesseract not installed — run: sudo apt install tesseract-ocr"

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        path = tmp.name
        captured = False

        try:
            # Try capture methods in order
            for method, cmd in [
                ("gnome-screenshot", ["gnome-screenshot", "-f", path]),
                ("scrot", ["scrot", path]),
                ("import", ["import", "-window", "root", path]),
            ]:
                if not shutil.which(method.split("-")[0]):
                    continue
                try:
                    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                    subprocess.run(cmd, capture_output=True, timeout=8, env=env)
                    if Path(path).exists() and Path(path).stat().st_size > 1000:
                        captured = True
                        break
                except Exception:
                    continue

            if not captured:
                # Try PIL as last resort
                try:
                    from PIL import ImageGrab

                    img = ImageGrab.grab()
                    img.save(path)
                    captured = True
                except Exception:
                    pass

            if not captured:
                return "Could not capture screen. " "Install scrot: sudo apt install scrot"

            # OCR
            r = subprocess.run(
                ["tesseract", path, "stdout", "-l", "eng", "--psm", "3"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            text = r.stdout.strip()
            if not text:
                return "Screen captured but no readable text found."

            # Clean up OCR output
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:3000]

        except Exception as e:
            return f"Screen read error: {e}"
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def take_screenshot(self) -> str:
        ts = int(time.time())
        path = Path.home() / f"screenshot_{ts}.png"
        for tool, cmd in [
            ("gnome-screenshot", ["gnome-screenshot", "-f", str(path)]),
            ("scrot", ["scrot", str(path)]),
        ]:
            if shutil.which(tool.split("-")[0]):
                try:
                    subprocess.run(cmd, timeout=10, capture_output=True)
                    if path.exists():
                        return str(path)
                except Exception:
                    continue
        return "Screenshot failed — install scrot or gnome-screenshot"

    # ── Weather ───────────────────────────────────────────────────────────────
    def get_weather(self) -> dict:
        import urllib.request

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._lat}&longitude={self._lon}"
            f"&current=temperature_2m,apparent_temperature,"
            f"relative_humidity_2m,is_day,weather_code,wind_speed_10m"
            f"&timezone=Asia%2FKolkata&forecast_days=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.loads(r.read().decode())
            c = data["current"]
            code = c.get("weather_code", 0)
            return {
                "temperature": c.get("temperature_2m"),
                "feels_like": c.get("apparent_temperature"),
                "humidity": c.get("relative_humidity_2m"),
                "condition": WEATHER_CODES.get(code, "unknown"),
                "wind_speed": c.get("wind_speed_10m"),
                "is_day": c.get("is_day", 1),
                "city": self._city,
                "ok": True,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_weather_summary(self) -> str:
        w = self.get_weather()
        if not w.get("ok"):
            return f"Can't fetch weather right now: {w.get('error', 'unknown error')}"
        now = self.get_current_time()
        feels = w["feels_like"]
        return (
            f"In {w['city']}, it's {w['temperature']}°C, feels like {feels}°C, "
            f"{w['condition']}, humidity {w['humidity']}%, "
            f"wind {w['wind_speed']} km/h. Local time: {now}"
        )

    def is_good_for_activity(self, activity: str) -> str:
        w = self.get_weather()
        if not w.get("ok"):
            return "Can't check weather right now."

        now_dt = datetime.now(self._tz)
        hour = now_dt.hour
        temp = w.get("temperature", 25)
        wind = w.get("wind_speed", 0)
        cond = w.get("condition", "")

        is_rain = "rain" in cond or "drizzle" in cond or "thunder" in cond
        is_clear = "clear" in cond or "sunny" in cond
        is_night = hour < 6 or hour >= 22
        is_hot = temp > 35
        is_cold = temp < 15
        is_windy = wind > 30

        time_str = now_dt.strftime("%I:%M %p")
        parts = []

        if is_rain:
            parts.append(f"No — it's {cond} right now")
        elif is_hot:
            if hour < 7 or hour > 18:
                parts.append(f"Should be okay — it's cooler now at {temp}°C")
            else:
                parts.append(f"Hot at {temp}°C — early morning or evening would be better")
        elif is_cold:
            parts.append(f"Yes, but dress warm — it's {temp}°C")
        elif is_clear and not is_night:
            parts.append(f"Great time — {temp}°C and {cond}")
        elif is_night:
            parts.append(f"It's {time_str}, {temp}°C — should be fine")
        else:
            parts.append(f"Should be fine — {temp}°C, {cond}")

        if is_windy:
            parts.append(f"though it's windy at {wind} km/h")

        return ", ".join(parts) + "."

    # ── Time ──────────────────────────────────────────────────────────────────
    def get_current_time(self) -> str:
        now = datetime.now(self._tz)
        return now.strftime("%I:%M %p, %A %B %d — %Z")

    # ── System info ───────────────────────────────────────────────────────────
    def get_system_info(self) -> str:
        """Returns raw data string. Brain formats it for speech."""
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            up_s = time.time() - psutil.boot_time()
            up_h = int(up_s // 3600)
            up_m = int((up_s % 3600) // 60)

            gpu = ""
            try:
                r = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if r.returncode == 0:
                    parts = r.stdout.strip().split(",")
                    gpu = (
                        f"NVIDIA {parts[0].strip()} — "
                        f"VRAM {parts[1].strip()}/{parts[2].strip()} MB, "
                        f"Temp {parts[3].strip()}°C"
                    )
            except Exception:
                pass

            result = (
                f"CPU {cpu}% — "
                f"RAM {mem.used // 1024**2}/{mem.total // 1024**2} MB "
                f"({mem.percent}%) — "
                f"Disk {disk.used // 1024**3}/{disk.total // 1024**3} GB "
                f"({disk.percent}%) — "
                f"Uptime {up_h}h {up_m}m"
            )
            if gpu:
                result += f" — {gpu}"
            return result
        except Exception as e:
            return f"System info error: {e}"

    # ── Files ─────────────────────────────────────────────────────────────────
    def read_file(self, path: str, max_chars: int = 4000) -> str:
        p = Path(path).expanduser()
        if not p.exists():
            return f"Not found: {path}"
        if p.is_dir():
            items = sorted(str(f.name) for f in p.iterdir())
            return "Contents: " + ", ".join(items[:50])
        try:
            content = p.read_text(errors="replace")
            if len(content) > max_chars:
                return content[:max_chars] + "\n...(truncated)"
            return content
        except Exception as e:
            return f"Error reading {path}: {e}"

    # ── Clipboard ─────────────────────────────────────────────────────────────
    def get_clipboard(self) -> str:
        for cmd in [
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    return r.stdout.strip()[:1000]
            except Exception:
                pass
        return ""

    # ── Logs ─────────────────────────────────────────────────────────────────
    def get_logs(self, service: str = "", lines: int = 50) -> str:
        cmd = (
            f"journalctl -u {service} -n {lines} --no-pager"
            if service
            else f"journalctl -n {lines} --no-pager"
        )
        out, err = self.run_command(cmd)
        return out or err or "No logs found"

    def web_search(self, query: str, max_results: int = 4) -> str:
        self.open_url(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                return f"Opened browser search for: {query}"
        try:
            with DDGS() as d:
                results = list(d.text(query, max_results=max_results))
            return "\n".join(
                f"{i+1}. {r.get('title','')}: {r.get('body','')[:150]}"
                for i, r in enumerate(results)
            )
        except Exception as e:
            return f"Opened browser search (API error: {e})"
