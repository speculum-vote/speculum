"""A monthly budget for the Anthropic API, kept by the code itself.

Every AI call (drafting, revising, checking claims against sources) records what it cost, from the token and search
counts the API returns, in data/ai_spend.json. Before each call, the step asks whether the month still has room for
it; when not, the step stops and says so. The account's own limit in the Anthropic console stays as a backstop
above this one.

The budget is SPECULUM_AI_BUDGET dollars a calendar month (UTC), default BUDGET. Prices are the list prices per
million tokens; when they change, update PRICES."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

BUDGET = 75.0
PRICES = {"opus": (4.0, 20.0), "sonnet": (2.0, 10.0), "haiku": (0.5, 2.5)}   # $ per million input, output tokens
SEARCH = 0.01                                                                  # $ per web search
EST = {"draft": 1.0, "check": 0.6, "revise": 0.15}                             # what one call may cost, at most-ish
PATH = Path(os.environ.get("SPECULUM_DATA", "data")) / "ai_spend.json"


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def limit() -> float:
    try:
        return float(os.environ.get("SPECULUM_AI_BUDGET") or BUDGET)
    except ValueError:
        return BUDGET


def cost(model: str, usage: dict | None) -> float:
    u = usage or {}
    tier = next((k for k in PRICES if k in (model or "")), "opus")
    pin, pout = PRICES[tier]
    tokens_in = (u.get("input_tokens") or 0) + 1.25 * (u.get("cache_creation_input_tokens") or 0) \
        + 0.05 * (u.get("cache_read_input_tokens") or 0)
    searches = ((u.get("server_tool_use") or {}).get("web_search_requests") or 0)
    return tokens_in * pin / 1e6 + (u.get("output_tokens") or 0) * pout / 1e6 + searches * SEARCH


def load(path: Path = None) -> dict:
    p = path or PATH
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def spent(path: Path = None, month: str | None = None) -> float:
    return float(((load(path).get("months") or {}).get(month or _month()) or {}).get("spent") or 0)


def allow(kind: str, path: Path = None) -> bool:
    """Is there room this month for one more call of this kind?"""
    have, cap = spent(path), limit()
    if have + EST.get(kind, 1.0) > cap:
        log.warning("AI budget: $%.2f of $%.2f spent this month; no more %s calls until next month", have, cap, kind)
        return False
    return True


def record(kind: str, model: str, usage: dict | None, path: Path = None) -> float:
    p = path or PATH
    c = cost(model, usage)
    d = load(p)
    d.setdefault("_how", "Spending on the Anthropic API by month, recorded by the code after each call (speculum/budget.py).")
    m = d.setdefault("months", {}).setdefault(_month(), {"spent": 0.0, "by": {}, "calls": 0})
    m["spent"] = round(m["spent"] + c, 4)
    m["by"][kind] = round(m["by"].get(kind, 0) + c, 4)
    m["calls"] = m.get("calls", 0) + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")
    return c
