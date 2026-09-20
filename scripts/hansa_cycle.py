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
SUB = ("fewer", "less", "loses", "lost", "minus", "away", "left", "eats")
MUL = ("each", "per", "times", "every")
ADD = ("more", "gains", "gain", "plus", "additional", "another", "gets")


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

    total = nums[0][2]
    for i in range(1, len(nums)):
        # Nearest keyword wins. In "gains 3 more and loses 1" the "loses"
        # belongs to the *next* pair, so a plain "keyword anywhere in the
        # window" test reads 3 as a subtraction. Proximity fixes that.
        before = re.findall(r"[a-z]+", t[nums[i - 1][1]:nums[i][0]])[::-1]
        after = re.findall(r"[a-z]+", t[nums[i][1]:nums[i][1] + 24])
        op = None
        for d in (0, 1, 2):
            for words in (before, after):
                if d < len(words):
                    w = words[d]
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
        v = nums[i][2]
        total = total - v if op == "sub" else \
            total * v if op == "mul" else total + v
    return total


def do_checkin(lines):
    st, body = http("POST", "/api/agents/checkin")
    lines.append(f"- checkin: `{st}` {brief(body)}")
    if isinstance(body, dict) and body.get("status") == "challenge_required":
        ans = answer_challenge(body.get("question"))
        lines.append(f"  - challenge: {body.get('question')!r}")
        lines.append(f"  - solved: `{ans}`")
        if ans is None:
            lines.append("  - SKIPPED: no numbers parsed")
            return
        st2, body2 = http("POST", "/api/agents/checkin/verify",
                          {"challenge_id": body.get("challenge_id"),
                           "challenge_answer": ans})
        lines.append(f"  - verify: `{st2}` {brief(body2)}")
        if st2 == 429:
            lines.append("  - NOTE: rate limited by Agent Hansa (per-IP). "
                         "Will retry on the next cycle.")


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
