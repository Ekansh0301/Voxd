"""
core/plugin_loader.py — Dynamic plugin discovery

Drop any .py file in ~/Downloads/flash-copilot/plugins/custom/
It gets auto-loaded. Each plugin is a dict:
  {
    'name':     'weather',
    'trigger':  ['weather', 'temperature', 'forecast'],  # keywords
    'handler':  fn(query: str) -> str,                   # returns response
  }

Example plugin file: plugins/custom/weather.py
  def setup():
      return {
          'name': 'weather',
          'trigger': ['weather', 'temperature'],
          'handler': lambda q: 'Weather plugin: ...'
      }
"""
import importlib.util
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("flash.plugins")


class PluginLoader:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = Path(plugins_dir) / "custom"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.plugins: list[dict] = []
        self._load_all()

    def _load_all(self):
        self.plugins = []
        for py_file in self.plugins_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "setup"):
                    plugin = mod.setup()
                    if isinstance(plugin, dict) and "name" in plugin:
                        self.plugins.append(plugin)
                        log.info(f"Plugin loaded: {plugin['name']}")
            except Exception as e:
                log.error(f"Plugin {py_file.name} failed: {e}")

    def reload(self):
        """Hot-reload all plugins."""
        self._load_all()
        log.info(f"Plugins reloaded: {len(self.plugins)} loaded")

    def match(self, text: str) -> Optional[dict]:
        """Return first plugin whose triggers appear in text."""
        tl = text.lower()
        for plugin in self.plugins:
            triggers = plugin.get("trigger", [])
            if any(t.lower() in tl for t in triggers):
                return plugin
        return None

    def run(self, text: str) -> Optional[str]:
        """Run matching plugin, return result or None."""
        plugin = self.match(text)
        if plugin:
            try:
                handler = plugin.get("handler")
                if callable(handler):
                    return handler(text)
            except Exception as e:
                log.error(f"Plugin {plugin['name']} error: {e}")
        return None

    @property
    def names(self) -> list[str]:
        return [p["name"] for p in self.plugins]
