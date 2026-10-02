import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.tools.site_actions import open_site, slug


def test_slug():
    assert slug("Two Sum") == "two-sum" and slug("  Git ") == "git"


def run(**kw):
    ctx = Context(desktop=False)
    out = asyncio.run(open_site(ctx, **kw))
    return out, ctx.actions


def test_shortcuts_fill_templates():
    out, actions = run(site="youtube", action="search", query="lofi beats")
    assert "search_query=lofi+beats" in actions[-1]
    out, actions = run(site="leetcode", action="problem", query="Two Sum")
    assert "leetcode.com/problems/two-sum/" in actions[-1]
    out, actions = run(site="quickref", action="topic", query="git")
    assert "quickref.me/git" in actions[-1]
    assert run(site="github", action="nonsense")[0].startswith("error")
    assert run(site="youtube", action="search")[0].startswith("error")  # needs a query


def test_blocked_sites_stay_blocked():
    with pytest.raises(Denied):
        run(site="moodle")
