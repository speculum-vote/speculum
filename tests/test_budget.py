import json

from speculum import budget


def test_cost_from_usage_matches_list_prices():
    u = {"input_tokens": 249634, "output_tokens": 14035, "server_tool_use": {"web_search_requests": 8}}
    assert round(budget.cost("claude-sonnet-5-5", u), 2) == 0.72        # the Nov. 9 test draft
    assert round(budget.cost("claude-opus-5-5", {"input_tokens": 100_000, "output_tokens": 1000}), 2) == 0.42


def test_calls_stop_when_the_month_is_spent(tmp_path, monkeypatch):
    p = tmp_path / "ai_spend.json"
    monkeypatch.setattr(budget, "PATH", p)
    monkeypatch.setenv("SPECULUM_AI_BUDGET", "1.9")
    assert budget.allow("draft")
    budget.record("draft", "claude-sonnet-5-5", {"input_tokens": 500_000})   # $1.00
    assert budget.allow("check") and not budget.allow("draft")              # 1.00 + 0.60 fits; 1.00 + 1.00 does not
    budget.record("check", "claude-opus-5-5", {"input_tokens": 100_000})     # $0.40
    m = json.loads(p.read_text())["months"][budget._month()]
    assert m["calls"] == 2 and round(m["spent"], 2) == 1.40 and set(m["by"]) == {"draft", "check"}
