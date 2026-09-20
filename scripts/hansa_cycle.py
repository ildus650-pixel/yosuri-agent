#!/usr/bin/env python3
"""AgentHansa autonomous cycle for a single agent.

Runs the documented 8-hour loop:
    1. GET  /api/agents/feed            personalized feed
    2. POST /api/agents/checkin         daily check-in (anti-bot math challenge)
    3. POST /api/agents/checkin/verify  answer the challenge
    4. GET  /api/agents/daily-quests    daily quest progress
    5. GET  /api/agents/earnings        wallet / earnings

Prints a plain-text report on stdout; exits non-zero only when the whole
cycle failed to reach the API (a challenge we cannot solve is reported in
the text, not raised, so the run still delivers a useful message).

Env:
    HANSA_API_KEY   required, tabb_...
    HANSA_BASE      optional, defaults to https://www.agenthansa.com
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("HANSA_BASE", "https://www.agenthansa.com").rstrip("/")
KEY = (os.environ.get("HANSA_API_KEY") or "").strip()
TIMEOUT = 60

# NOTE: the key is validated in main(), not at import time, so the challenge
# solver stays importable for tests.


# ---------------------------------------------------------------- HTTP helper

def call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    """Return (status, parsed-json-or-raw-text). Never raises for HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # network / DNS / timeout
        return 0, f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------- challenge math solver

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

_PLUS = ("gains", "gain", "gets", "receives", "finds", "more than", "more",
         "buys", "adds", "wins", "earns")
_MINUS = ("loses", "lose", "gives away", "fewer", "less than", "less",
          "spends", "eats", "sells", "gives", "away")

# How far either side of a number to look for its operator word.
_WINDOW = 40


def _tokens(text: str) -> list[int]:
    """Numbers in order of appearance, with number words converted."""
    out: list[int] = []
    for tok in re.findall(r"\b\d+\b|\b[A-Za-z]+\b", text.lower()):
        if tok.isdigit():
            out.append(int(tok))
        elif tok in _NUM_WORDS:
            out.append(_NUM_WORDS[tok])
    return out


def solve(question: str) -> int | None:
    """Solve AgentHansa's templated word problems.

    Observed shapes (all verified against live challenges):
      "8 chefs each carry 7 marbles. How many marbles in total?"  -> 8 * 7
      "A squirrel has 22 cookies. A monkey has 21 fewer. ..."     -> 22 - 21
      "A cat has eight fish. It gains 3 more and loses 1. ..."    -> 8 + 3 - 1
      "A penguin has 19 coins. A chef has 6 more than the penguin." -> 19 + 6
    Returns None when the shape is not recognised (caller reports it).
    """
    if not question:
        return None
    low = question.lower()
    nums = _tokens(question)
    if not nums:
        return None

    # A lone number is only trustworthy when the wording asks for a total,
    # e.g. "A cat has 4 fish. How many fish in total?" -> 4. Otherwise an
    # operation was implied that we failed to parse: refuse rather than guess,
    # because a wrong answer burns the challenge and the rate limit is tight.
    if len(nums) == 1:
        return nums[0] if re.search(r"\b(total|altogether|how many)\b", low) else None

    # "N ... each ... M ... in total" -> product
    if "each" in low and len(nums) >= 2:
        product = 1
        for n in nums[:2]:
            product *= n
        return product

    # Otherwise: the first number is the base, later numbers add or subtract.
    # The operator word may sit on either side of the number, so pick the
    # NEAREST keyword in either direction:
    #   "It gains 3 more and loses 1"  -> for 1, "loses" is nearer than "more"
    #   "A robot has 9 fewer"          -> the keyword trails the number
    total = nums[0]
    for n in nums[1:]:
        idx = low.find(str(n))
        if idx < 0:
            return None
        sign = _operator_sign(low, idx, len(str(n)))
        if sign is None:
            return None  # ambiguous -> do not guess
        total += n * sign
    return total


def _operator_sign(text: str, start: int, length: int) -> int | None:
    """Sign of the operator nearest the number at text[start:start+length]."""
    best: tuple[int, int] | None = None  # (distance, sign)
    end = start + length
    for sign, words in ((+1, _PLUS), (-1, _MINUS)):
        for word in words:
            for m in re.finditer(re.escape(word), text):
                ws, we = m.start(), m.end()
                if we <= start:
                    dist = start - we          # word sits before the number
                elif ws >= end:
                    dist = ws - end            # word sits after the number
                else:
                    continue                   # overlapping the number itself
                if dist > _WINDOW:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, sign)
    return best[1] if best else None


def resolve_challenge(obj: object, verify_path: str) -> object:
    """If the response is a challenge, solve it and post the answer."""
    if not isinstance(obj, dict) or obj.get("status") != "challenge_required":
        return obj
    question = obj.get("question") or ""
    answer = solve(question)
    if answer is None:
        return {"status": "challenge_unsolved", "question": question}
    code, res = call("POST", verify_path, {
        "challenge_id": obj.get("challenge_id"),
        "challenge_answer": answer,
    })
    if isinstance(res, dict):
        res.setdefault("_solved_question", question)
        res.setdefault("_computed_answer", answer)
    return res


# ------------------------------------------------------------------- cycle

def brief(value: object, limit: int = 700) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def main() -> int:
    if not KEY:
        print("HANSA_API_KEY is not set", file=sys.stderr)
        return 2

    lines: list[str] = []

    # 1. feed
    feed_code, feed = call("GET", "/api/agents/feed")
    lines.append(f"*AgentHansa cycle*")
    lines.append("")
    lines.append(f"*Feed* (HTTP {feed_code})")
    if isinstance(feed, dict):
        for k in ("urgent", "open_quests", "community_tasks", "daily_quest",
                  "pending_quests", "summary"):
            if k in feed:
                lines.append(f"• {k}: {brief(feed[k], 400)}")
        if not any(k in feed for k in ("urgent", "open_quests", "summary")):
            lines.append(f"• {brief(feed)}")
    else:
        lines.append(f"• {brief(feed)}")

    # 2/3. check-in with challenge
    check_code, check = call("POST", "/api/agents/checkin")
    check = resolve_challenge(check, "/api/agents/checkin/verify")
    lines.append("")
    lines.append(f"*Check-in* (HTTP {check_code})")
    if isinstance(check, dict):
        for k in ("status", "streak", "amount", "credited", "balance", "message",
                  "_computed_answer", "_solved_question"):
            if check.get(k) is not None:
                lines.append(f"• {k}: {brief(check[k], 300)}")
        if check.get("status") == "challenge_unsolved":
            # Print the wording verbatim: without it the failure cannot be
            # diagnosed or used to extend the solver.
            lines.append(f"• unsolved challenge wording: {brief(check.get('question'), 300)}")
    else:
        lines.append(f"• {brief(check)}")

    # 4. daily quests
    dq_code, dq = call("GET", "/api/agents/daily-quests")
    lines.append("")
    lines.append(f"*Daily quests* (HTTP {dq_code})")
    lines.append(f"• {brief(dq, 600)}")

    # 5. earnings
    earn_code, earn = call("GET", "/api/agents/earnings")
    lines.append("")
    lines.append(f"*Earnings* (HTTP {earn_code})")
    if isinstance(earn, dict):
        for k in ("balance", "total_earned", "pending", "held", "currency"):
            if earn.get(k) is not None:
                lines.append(f"• {k}: {earn[k]}")
        if not any(k in earn for k in ("balance", "total_earned", "pending")):
            lines.append(f"• {brief(earn)}")
    else:
        lines.append(f"• {brief(earn)}")

    print("\n".join(lines))
    # Fail loudly only if we never reached the API at all.
    return 0 if (feed_code or check_code or dq_code or earn_code) else 1


if __name__ == "__main__":
    sys.exit(main())
