import json

from speculum import interpret


def chains(n):
    return [{"id": f"c{i}", "date": f"2025-01-{i + 1:02d}", "enacted": False} for i in range(n)]


def test_failed_drafts_use_up_the_limit(tmp_path):
    calls = []
    def fail(ch):
        calls.append(ch["id"])
        raise ValueError("drafter returned no JSON")
    done = interpret.draft_missing(chains(10), tmp_path / "drafts", limit=3, call=fail, today="2026-11-09")
    assert done == [] and calls == ["c0", "c1", "c2"]
    f = json.loads((tmp_path / "draft_failures.json").read_text())
    assert set(f) == {"c0", "c1", "c2"} and f["c0"]["times"] == 1 and "no JSON" in f["c0"]["error"]


def test_a_failed_chain_waits_a_week_then_is_tried_again(tmp_path):
    d = tmp_path / "drafts"
    interpret.draft_missing(chains(5), d, limit=1, call=lambda ch: 1 / 0, today="2026-11-01")
    seen = []
    ok = lambda ch: seen.append(ch["id"]) or {"mechanism": "x"}
    assert interpret.draft_missing(chains(5), d, limit=1, call=ok, today="2026-11-07") == ["c1"]
    assert interpret.draft_missing(chains(5), d, limit=1, call=ok, today="2026-11-09") == ["c0"]
    assert "c0" not in json.loads((tmp_path / "draft_failures.json").read_text())


def test_no_new_draft_after_the_time_budget(tmp_path):
    t = [0.0]
    def slow(ch):
        t[0] += 20 * 60
        return {"mechanism": "x"}
    done = interpret.draft_missing(chains(10), tmp_path / "drafts", limit=5, call=slow, today="2026-11-09",
                                   budget_min=30, clock=lambda: t[0])
    assert done == ["c0", "c1"]


def test_the_draft_comes_from_the_record_tool():
    body = {"stop_reason": "tool_use", "content": [{"type": "text", "text": "Done."},
            {"type": "tool_use", "name": "record_draft", "input": {"outcomes": [{"quote": 'He said "no".'}]}}]}
    assert interpret.parse_draft(body)["outcomes"][0]["quote"] == 'He said "no".'


def test_a_cut_off_answer_says_so():
    import pytest
    with pytest.raises(ValueError, match="cut off at the token limit"):
        interpret.parse_draft({"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"outcomes": [{"cl'}]})


def test_text_json_still_parses_with_trailing_words():
    body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": 'Here it is: {"a": 1} Hope that helps {x}'}]}
    assert interpret.parse_draft(body) == {"a": 1}
