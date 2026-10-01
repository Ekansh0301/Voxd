from tars.tools.browser import compact_snapshot, short

SNAP = """Snapshot

uid=e11 body
  uid=e0 h1 "Internship form" text="Internship form"
  uid=e1 input "Full name"
  uid=e2 input
  uid=e3 input "Email address"
  uid=e5 select value="2025"
  uid=e7 a "Help page" href="data:text/html,..." text="Help page"
  uid=e8 button "Send" text="Send"
  uid=e12 button "Send" text="Send"
  uid=e9 button tag=div text="Cancel"
  uid=e20 span text="H"
  uid=e21 span text="i"
  uid=e10 p text="Some paragraph text"
"""


def test_compact_snapshot_names_and_uids():
    text, names = compact_snapshot(SNAP)
    assert 'input "Full name"' in text and 'input "unnamed input"' in text
    assert names["Full name"] == "e1" and names["Send"] == "e8" and names["Send (2)"] == "e12"
    assert names["Cancel"] == "e9"  # div with role=button
    assert 'text "Hi"' in text  # per-letter spans joined
    assert 'p "Some paragraph text"' in text and "body" not in text


def test_short_url_for_speech():
    assert short("https://outlook.office365.com/mail/inbox/id/AAQk") == "outlook.office365.com"
    assert short("https://www.github.com/x") == "github.com"
    assert short("data:text/html,abc") == "this page"
