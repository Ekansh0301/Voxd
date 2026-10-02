"""Built-in tools. `default_registry()` is what the Conductor sees in Phase 2."""

from tars.agent.tools import Registry
from tars.memory.store import Memory


def default_registry(memory: Memory | None = None) -> Registry:
    from tars.tools import desktop, files, screen, shell, system, vision
    from tars.tools import memory as memory_tools

    reg = Registry()
    for module in (system, files, shell, desktop, screen, vision):
        module.register(reg)
    memory_tools.register(reg, memory or Memory())
    from tars.tools import apps, code, context, keys, music

    apps.register(reg, apps.AppRegistry())
    code.register(reg)
    music.register(reg)
    keys.register(reg)
    context.register(reg)
    return reg
