"""Built-in tools. `default_registry()` builds the full set the model can call."""

from tars.agent.tools import Registry
from tars.memory.store import Memory
from tars.skills.store import Skills


def default_registry(memory: Memory | None = None, skills: Skills | None = None) -> Registry:
    from tars.tools import desktop, files, screen, shell, system, vision
    from tars.tools import memory as memory_tools

    reg = Registry()
    for module in (system, files, shell, desktop, screen, vision):
        module.register(reg)
    memory_tools.register(reg, memory or Memory())
    from tars.tools import (
        apps,
        ask_ai,
        code,
        context,
        documents,
        keys,
        locate,
        music,
        research,
        routines,
        site_actions,
    )

    apps.register(reg, apps.AppRegistry())
    code.register(reg)
    music.register(reg)
    keys.register(reg)
    context.register(reg)
    research.register(reg)
    locate.register(reg)
    routines.register(reg, skills or Skills())
    ask_ai.register(reg)
    documents.register(reg)
    site_actions.register(reg)
    return reg
