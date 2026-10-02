from tars.skills.store import Skills, _match_template, generalize, tokens

SP = [
    {
        "tool": "read_screen",
        "args": {"window": "super productivity"},
        "result": "window 'Super Productivity'\n  menu item 'Planner'\n  menu item 'Today'",
    },
    {"tool": "click", "args": {"name": "Planner"}, "result": "select on menu item 'Planner': done"},
]
GPT = [
    {"tool": "open_url", "args": {"url": "chatgpt"}, "result": "opened https://chatgpt.com/"},
    {"tool": "web_read", "args": {}, "result": 'https://chatgpt.com/\nfield "Chat with ChatGPT"'},
    {
        "tool": "web_fill",
        "args": {"name": "Chat with ChatGPT", "text": "what the capital of Australia is"},
        "result": "typed",
    },
    {"tool": "web_key", "args": {"key": "Enter"}, "result": "press_key Enter"},
    {"tool": "web_read", "args": {"mode": "text"}, "result": "Canberra"},
]


def test_tokens_drop_politeness_and_stamp():
    assert tokens("[Thu 01 Oct 2026, 10:42 AM] Could you please open GitHub?") == ["open", "GitHub"]


def test_generalize_and_match():
    trigger, steps = generalize("In Super Productivity, switch to the Planner view.", SP)
    assert trigger == ["In", "{window}", "switch", "to", "the", "{name}", "view"]
    assert steps[1]["args"]["name"] == "{name}"
    slots = _match_template(trigger, tokens("in Super Productivity switch to the Today view"))
    assert slots == {"window": "Super Productivity", "name": "Today"}


def test_model_written_text_is_not_learned():
    steps = [dict(s) for s in GPT]
    steps[2] = {
        "tool": "web_fill",
        "args": {"name": "Chat with ChatGPT", "text": "Kindly reply with Australia's capital city"},
        "result": "typed",
    }
    assert generalize("Ask ChatGPT what the capital of Australia is", steps) is None


def test_learn_then_replay_plan(tmp_path):
    sk = Skills(tmp_path / "skills.db")
    assert (
        sk.learn("Ask ChatGPT what the capital of Australia is", GPT, "It says Canberra.")
        == "learned"
    )
    got = sk.match("ask chatgpt what the capital of Japan is")
    assert got is not None and got.slots["text"] == "what the capital of Japan is"
    plan = got.plan()
    assert [p["tool"] for p in plan] == ["open_url", "web_read", "web_fill", "web_key", "web_read"]
    assert plan[2]["args"]["text"] == "what the capital of Japan is"
    assert sk.match("open youtube") is None


def test_one_step_or_failed_turns_not_learned(tmp_path):
    sk = Skills(tmp_path / "skills.db")
    assert (
        sk.learn(
            "Play Believer",
            [{"tool": "play_music", "args": {"song": "Believer"}, "result": "playing"}],
            "Playing.",
        )
        == ""
    )
    assert (
        sk.learn(
            "In Super Productivity, switch to the Planner view.", SP, "Sorry, I couldn't find it."
        )
        == ""
    )


def test_retired_after_failures(tmp_path):
    sk = Skills(tmp_path / "skills.db")
    sk.learn("In Super Productivity, switch to the Planner view.", SP, "Done.")
    s = sk.match("in super productivity switch to the today view")
    for _ in range(2):
        sk.learn("x", [{"tool": "click", "args": {}, "result": "error: nothing named"}], "", used=s)
    assert sk.match("in super productivity switch to the today view") is None


def test_routines(tmp_path):
    sk = Skills(tmp_path / "skills.db")
    sk.add_routine(
        "Study Mode", ["open my project in VS Code", "play my phonk playlist", "set volume to 30"]
    )
    assert sk.routine_for("start study mode")[1][1] == "play my phonk playlist"
    assert sk.routine_for("study mode please") is not None
    assert sk.routine_for("study hard") is None


def test_values_derived_from_the_request_are_not_learned():
    calc = [
        {"tool": "open_app", "args": {"name": "calculator"}, "result": "opened Calculator"},
        {
            "tool": "type_text",
            "args": {"text": "12*7", "then_key": "Enter", "window": "calculator"},
            "result": "typed 4 characters",
        },
    ]
    assert generalize("Open the calculator and work out 12 times 7", calc) is None
