from tars.agent.loop import _budget, _fit, _size


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
        {"role": "user", "content": "q"},
        {"role": "tool", "content": "y" * 500},
        {"role": "tool", "content": "z" * 500},
        {"role": "tool", "content": "w" * 500},
    ]
    _fit(msgs, budget=10000)
    assert msgs[2]["content"] == "y" * 500


def test_oldest_history_dropped_before_this_turn_is_cut():
    history = []
    for i in range(8):
        history += [{"role": "user", "content": f"old question {i} " + "q" * 300},
                    {"role": "assistant", "content": f"old answer {i} " + "a" * 300}]  # fmt: skip
    msgs = [{"role": "system", "content": "s"}, *history,
            {"role": "user", "content": "explain fetch_gated.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "code " * 500}]  # fmt: skip
    _fit(msgs, budget=4000)
    assert _size(msgs) <= 4000
    assert msgs[-1]["content"] == "code " * 500  # the file this turn read stays whole
    assert "old question 0" not in str(msgs)  # the oldest turns went first
    assert any("old answer 7" in str(m.get("content")) for m in msgs)  # the latest stayed


def test_latest_result_cut_only_as_last_resort():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "read it"},
            {"role": "tool", "content": "x" * 9000}]  # fmt: skip
    _fit(msgs, budget=3000)
    assert _size(msgs) <= 3000 and "cut to fit" in msgs[-1]["content"]


def test_budget_shrinks_with_the_tool_list():
    sys_msg = [{"role": "system", "content": "s" * 3200}]
    few = _budget(sys_msg, [{"x": "y" * 1000}], 400)
    many = _budget(sys_msg, [{"x": "y" * 18000}], 400)
    assert many < few and many > 8000  # ~6k-token prefix still leaves room at 10240


def test_unrequested_actions_flagged():
    from tars.agent.loop import _mentioned

    assert not _mentioned({"path": "~/Documents"}, "Summarize Downloads/readme.txt for me.")
    assert _mentioned({"path": "~/Downloads/old.log"}, "Delete old.log from my Downloads.")
