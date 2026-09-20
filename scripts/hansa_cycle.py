#!/usr/bin/env python3
"""Agent Hansa autonomous cycle.

Documented 8-hour loop for one agent:
    GET  /api/agents/feed            -> what to do next
    POST /api/agents/checkin         -> returns a math challenge
    POST /api/agents/checkin/verify  -> solve it, claim daily USDC
    GET  /api/agents/daily-quests    -> quest bonus progress
    GET  /api/agents/earnings        -> balance

Prints a report to stdout; the workflow sends it to Telegram and commits it.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("HANSA_BASE", "https://www.agenthansa.com")
KEY = os.environ.get("HANSA_API_KEY", "").strip()
NAME = os.environ.get("AGENT_NAME", "agent")
UA = "hansa-cycle/1.0"

WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
SUB = ("fewer", "less", "loses", "lost", "minus", "away", "left", "eats",
       "spends", "drops", "gives", "breaks", "sells")
MUL = ("each", "per", "times", "every")
ADD = ("more", "gains", "gain", "plus", "additional", "another", "gets",
       "finds", "found", "receives", "collects", "wins", "buys", "adds")
# Unary modifiers applied to the number they sit in front of:
# "A captain doubles its 2 coins" -> that 2 becomes 4.
UNARY = ((("doubles", "double", "twice"), 2.0),
         (("triples", "triple"), 3.0),
         (("halves", "half"), 0.5))


def http(method, path, body=None, timeout=45):
    """Return (status, parsed-json-or-text). Never raises on HTTP error."""
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, safe_json(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, safe_json(raw)
    except Exception as e:  # noqa: BLE001 - report, never crash the run
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def safe_json(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_text": raw[:600]}


def answer_challenge(question):
    """Solve the template math word problems. Returns int or None."""
    if not question:
        return None
    t = question.lower()
    for w, n in WORDS.items():
        t = re.sub(r"\b" + w + r"\b", str(n), t)
    # (start, end, value) - `end` is needed to slice the text AFTER the number.
    nums = [(m.start(), m.end(), int(m.group())) for m in re.finditer(r"\d+", t)]
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0][2]

    total = None
    for i in range(len(nums)):
        # Nearest keyword wins. In "gains 3 more and loses 1" the "loses"
        # belongs to the *next* pair, so a plain "keyword anywhere in the
        # window" test reads 3 as a subtraction. Proximity fixes that.
        prev_end = nums[i - 1][1] if i else 0
        before = re.findall(r"[a-z]+", t[prev_end:nums[i][0]])[::-1]
        after = re.findall(r"[a-z]+", t[nums[i][1]:nums[i][1] + 24])

        # Unary modifier. "doubles its 2 coins" scales the *number*;
        # "halves them" scales the running *total*, so the following pronoun
        # decides where the factor lands.
        v = float(nums[i][2])
        for words_, factor in UNARY:
            hit = next((k for k, w in enumerate(before) if w in words_), None)
            if hit is None:
                continue
            after_unary = before[hit - 1] if hit >= 1 else ""
            if after_unary in ("them", "it", "those", "these") and total is not None:
                total *= factor
            else:
                v *= factor
            break

        if total is None:
            total = v
            continue

        op = None
        for d in (0, 1, 2):
            for words_ in (before, after):
                if d < len(words_):
                    w = words_[d]
                    if w in SUB:
                        op = "sub"
                    elif w in MUL:
                        op = "mul"
                    elif w in ADD:
                        op = "add"
                    if op:
                        break
            if op:
                break
        total = total - v if op == "sub" else \
            total * v if op == "mul" else total + v

    return int(total) if total is not None and float(total).is_integer() \
        else None


def do_checkin(lines, attempts=3):
    """Check in, solving the challenge. Retries with a *new* challenge if the
    answer is rejected - the API explicitly offers that ("Wrong answer. Call
    POST /api/agents/checkin again for a new challenge"), which makes an
    unseen template a retry rather than a failure."""
    for n in range(1, attempts + 1):
        st, body = http("POST", "/api/agents/checkin")
        if not isinstance(body, dict):
            lines.append(f"  - attempt {n}: `{st}` {brief(body)}")
            continue
        if body.get("status") != "challenge_required":
            lines.append(f"  - attempt {n}: `{st}` {brief(body)}")
            return  # already checked in, nothing to solve
        q = body.get("question")
        ans = answer_challenge(q)
        lines.append(f"  - attempt {n}: {q!r} -> `{ans}`")
        if ans is None:
            continue  # unparsed template; a fresh challenge may parse
        st2, body2 = http("POST", "/api/agents/checkin/verify",
                          {"challenge_id": body.get("challenge_id"),
                           "challenge_answer": ans})
        lines.append(f"    verify `{st2}`: {brief(body2, 200)}")
        if st2 == 200:
            return
        if st2 == 429:
            lines.append("    NOTE: rate limited by Agent Hansa (per-IP) - "
                         "will retry next cycle.")
            return
        time.sleep(2)
    lines.append("  - gave up after retries; no change this cycle")


def brief(obj, limit=260):
    if isinstance(obj, (dict, list)):
        s = json.dumps(obj, ensure_ascii=False)
    else:
        s = str(obj)
    s = " ".join(s.split())
    return s[:limit] + ("…" if len(s) > limit else "")


def main():
    if not KEY:
        print("HANSA_API_KEY is not set; nothing to do.")
        return 0

    lines = [f"*Agent Hansa cycle — {NAME}*", ""]
    for label, path in (("feed", "/api/agents/feed"),
                        ("daily-quests", "/api/agents/daily-quests"),
                        ("earnings", "/api/agents/earnings")):
        st, body = http("GET", path)
        lines.append(f"*- {label}:* `{st}`")
        lines.append(f"  {brief(body, 700)}")
        lines.append("")
        time.sleep(1)

    lines.append("*- action*")
    do_checkin(lines)

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
