import pytest

from tars.sites import SiteRegistry


@pytest.fixture(scope="module")
def reg():
    return SiteRegistry()


@pytest.mark.parametrize(
    "url",
    ["https://courses.iiit.ac.in/my/", "http://ims.iiit.ac.in/", "portals.iiit.ac.in/x"],
)
@pytest.mark.parametrize("action", ["open", "read", "click", "type"])
def test_college_sites_are_blocked_for_everything(reg, url, action):
    d = reg.check(url, action)
    assert not d.allowed and "blocked" in d.reason


def test_practice_sites_open_only(reg):
    assert reg.check("https://monkeytype.com/", "open").allowed
    assert not reg.check("https://monkeytype.com/", "type").allowed
    assert not reg.check("https://www.keybr.com/", "read").allowed


def test_outlook_full_and_subdomain_match(reg):
    assert reg.check("https://outlook.office365.com/mail/inbox", "type").allowed
    assert reg.site_for_url("https://outlook.office.com/mail/").key == "outlook"


def test_unlisted_site_defaults_to_navigate(reg):
    assert reg.check("https://example.org/page", "read").allowed
    assert not reg.check("https://example.org/page", "submit").allowed


def test_similar_hosts_do_not_match(reg):
    assert reg.site_for_url("https://notgithub.com/") is None
    assert reg.site_for_url("https://gist.github.com/").key == "github"


@pytest.mark.parametrize(
    "spoken,key",
    [("outlook", "outlook"), ("outluk", "outlook"), ("cheat sheet", "cheatsheet"),
     ("Chat GPT", "chatgpt"), ("typing practice", "keybr"), ("AI humanize", "aihumanize")],
)  # fmt: skip
def test_resolve_spoken_names(reg, spoken, key):
    assert reg.resolve(spoken).key == key


def test_resolve_unknown_returns_none(reg):
    assert reg.resolve("banana republic") is None


@pytest.mark.parametrize("spoken", ["cloud", "you", "banana", "cheat"])
def test_resolve_does_not_overmatch(reg, spoken):
    assert reg.resolve(spoken) is None
