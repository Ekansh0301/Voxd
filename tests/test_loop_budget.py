from tars.agent.loop import _fit


def test_older_tool_results_shortened_to_fit():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "do it"}]
    for i in range(8):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": str(i)}]})
        msgs.append(
            {"role": "tool", "tool_call_id": str(i), "content": f"result {i} " + "x" * 2400}
        )
    _fit(msgs, budget=8000)
    tools = [m["content"] for m in msgs if m["role"] == "tool"]
    assert all(len(t) > 2000 for t in tools[-2:])  # the latest two stay whole
    assert "shortened" in tools[0] and tools[0].startswith("result 0")
    assert sum(len(str(m.get("content") or "")) for m in msgs[1:]) <= 8000 + 2000


def test_small_conversations_untouched():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "tool", "content": "y" * 500},
        {"role": "tool", "content": "z" * 500},
        {"role": "tool", "content": "w" * 500},
    ]
    _fit(msgs)
    assert msgs[1]["content"] == "y" * 500


def test_unrequested_actions_flagged():
    from tars.agent.loop import _mentioned

    assert not _mentioned({"path": "~/Documents"}, "Summarize Downloads/readme.txt for me.")
    assert _mentioned({"path": "~/Downloads/old.log"}, "Delete old.log from my Downloads.")
