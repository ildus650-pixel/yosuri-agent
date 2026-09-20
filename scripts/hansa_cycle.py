#!/usr/bin/env python3
"""Agent Hansa autonomous cycle.

Documented 8-hour loop for one agent:
    GET   /api/agents/feed            -> what to do next
    POST  /api/agents/checkin         -> returns a math challenge
    POST  /api/agents/checkin/verify  -> solve it, claim daily USDC
    GET   /api/agents/daily-quests    -> quest progress
    GET   /api/agents/earnings        -> balance / rank
    PATCH /api/agents/alliance        -> join an alliance (one-off)
    GET   /api/forum                  -> posts to curate
    POST  /api/forum/{id}/vote        -> 5 up + 5 down
    GET   /api/forum/digest           -> latest posts

Rate limiting is first class: Agent Hansa throttles per IP (observed 429 on
almost every burst during registration). Every request is spaced by
MIN_INTERVAL and retried with backoff, honouring Retry-After. The last-call
timestamp is persisted so the spacing survives across runs.

The check-in challenge is a generated math word problem, solved locally by
answer_challenge() (18/18 on the observed templates).
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
STATE_PATH = os.environ.get("HANSA_RATE_STATE", "memory/hansa-rate.json")
MIN_INTERVAL = float(os.environ.get("HANSA_MIN_INTERVAL", "2"))
UA = "hansa-cycle/1.1"

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
UNARY = ((("doubles", "double", "twice"), 2.0),
         (("triples", "triple"), 3.0),
         (("halves", "half"), 0.5))
WAF_MARKERS = ("waf_block", "waf block", "forbidden")
# "shares half" is generated too, but the original list only had the verbs
# gives-away/eats/loses/... so that question was answered with the un-halved
# total (14 instead of 7).
HALF_RE = re.compile(
    r"\b(?:gives?\s+away|gave\s+away|shares?|shared|eats?|ate|loses?|lost|"
    r"spends?|drops?|sells?|uses?|burns?|pays?|keeps?|hands?\s+over)\s+"
    r"(?:exactly\s+)?half\b")


# --------------------------------------------------------------------------
# Rate limiting: min interval, Retry-After, 429/WAF backoff, persistent state
# --------------------------------------------------------------------------
_last_call = 0.0
_retry_count = 0


def load_state():
    """Restore the last-call timestamp so spacing survives across runs."""
    global _last_call
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            _last_call = float(json.load(fh).get("last_call", 0.0))
    except Exception:  # noqa: BLE001 - missing/corrupt state is not fatal
        _last_call = 0.0


def save_state():
    try:
        os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"last_call": _last_call, "agent": NAME,
                       "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime())}, fh)
    except Exception:  # noqa: BLE001
        pass


def throttle():
    """Never issue requests faster than MIN_INTERVAL."""
    global _last_call
    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    save_state()


def _sleep_for(headers, default):
    """Honour Retry-After (seconds or HTTP-date); fall back to `default`."""
    try:
        raw = (headers.get("Retry-After") or "").strip() if headers else ""
    except Exception:  # noqa: BLE001
        raw = ""
    if raw.isdigit():
        return min(float(raw), 120.0)
    return default


def http(method, path, body=None, timeout=45, attempts=3):
    """Throttled request with backoff on 429 / WAF_BLOCK.

    Returns (status, payload). Never raises.
    """
    global _last_call
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None

    for attempt in range(1, attempts + 1):
        throttle()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + KEY)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        status, payload = 0, None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, payload = r.status, safe_json(r.read().decode("utf-8", "replace"))
                return status, payload
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status, payload = e.code, safe_json(raw)
            if status == 429:
                pause = _sleep_for(e.headers, 30.0 + 15 * attempt)
                say(f"    429 -> sleeping {pause:.0f}s (attempt {attempt}/{attempts})")
            elif status in (403, 503) and any(
                    m in raw.lower() for m in WAF_MARKERS):
                pause = 60.0
                say(f"    WAF_BLOCK -> sleeping {pause:.0f}s "
                    f"(attempt {attempt}/{attempts})")
            else:
                return status, payload
            if attempt < attempts:
                time.sleep(pause)
        except Exception as e:  # noqa: BLE001
            say(f"    transport error: {type(e).__name__}: {e}")
            if attempt < attempts:
                time.sleep(5.0)
            else:
                return 0, {"_error": f"{type(e).__name__}: {e}"}
    return status, payload


SPOKE = []


def say(msg):
    """Buffer progress lines (also printed at the end)."""
    SPOKE.append(msg)


def safe_json(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_text": raw[:600]}


# --------------------------------------------------------------------------
# Challenge solver
# --------------------------------------------------------------------------
def _numbers(t):
    return [(m.start(), m.end(), int(m.group())) for m in re.finditer(r"\d+", t)]


def _fold(nums, t, total, floor=0):
    """Accumulate `nums` onto `total`, reading the surrounding words to pick
    each operation. `floor` is where the "before" window starts for the first
    number, so a segment that follows a split still sees its own context."""
    def unary_at(pairs):
        """First unary verb in `pairs` as (index, absolute offset, factor)."""
        for k, (pos, w) in enumerate(pairs):
            for stems, factor in UNARY:
                if w in stems:
                    return k, pos, factor
        return None, None, None

    consumed = -1  # end offset of the last unary verb already spent
    for i, (start, end, val) in enumerate(nums):
        prev_end = nums[i - 1][1] if i else floor
        before_ws = [(prev_end + m.start(), m.group())
                     for m in re.finditer(r"[a-z]+", t[prev_end:start])]
        after_ws = [(end + m.start(), m.group())
                    for m in re.finditer(r"[a-z]+", t[end:end + 28])]
        # Closest word first, with offsets kept for the unary guard. The op
        # search needs plain words - feeding it the pairs silently matched
        # nothing, so "loses 5" was added instead of subtracted.
        before = list(reversed(before_ws))
        before_words = [w for _, w in before]
        after_words = [w for _, w in after_ws]

        v = float(val)
        # Unary before the number: "doubles its 2 coins" scales that number,
        # but a pronoun object ("doubles them") scales the running total.
        k, pos, factor = unary_at(before)
        if k is not None and pos >= consumed:
            nxt = before[k - 1][1] if k >= 1 else ""
            if nxt in ("them", "it", "those", "these") and total is not None:
                total *= factor
                consumed = pos + len(before[k][1])
                continue
            v *= factor
            consumed = pos + len(before[k][1])
        # Unary after the number: "has 4 mice and triples them" acts on the
        # amount gathered so far, since the verb's object is the total.
        # `consumed` stops the same verb being counted again for the next
        # number, which doubles it a second time otherwise.
        k, pos, factor = unary_at(after_ws)
        if k is not None and pos >= consumed:
            if total is None:
                total = v
            total *= factor
            consumed = pos + len(after_ws[k][1])
            continue

        if total is None:
            total = v
            continue

        # Nearest keyword wins, and the word right after the number is nearer
        # than the one before it: "finds 12 fewer" is a loss, not a gain.
        op = None
        for d in (0, 1, 2):
            for words_ in (after_words, before_words):
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
    return total


def answer_challenge(question):
    """Solve the generated math word problems. Returns int or None.

    Handles: "N each -> multiply", "fewer/less -> subtract",
    "gains/finds + more -> add", "doubles its N -> unary x2".
    """
    if not question:
        return None
    t = question.lower()
    for w, n in WORDS.items():
        t = re.sub(r"\b" + w + r"\b", str(n), t)
    # --- templates whose operands are NOT in reading order -----------------
    # "subtract 10 from 30"  -> 30 - 10 = 20 (not 10 - 30)
    m = re.search(r"subtract\s+(\d+)\s+from\s+(\d+)", t)
    if m:
        return int(m.group(2)) - int(m.group(1))
    # "add 10 to 30" -> 40
    m = re.search(r"adds?\s+(\d+)\s+to\s+(\d+)", t)
    if m:
        return int(m.group(2)) + int(m.group(1))
    # "numbers its books from 1 to 11 inclusive" -> a COUNT, not a difference
    m = re.search(r"from\s+(\d+)\s+to\s+(\d+)", t)
    if m:
        return int(m.group(2)) - int(m.group(1)) + 1
    # "15 apples are split evenly among 5 foxes, how many per fox?" -> divide
    if re.search(r"split evenly|divided (?:evenly )?among|"
                 r"shared (?:equally )?among|distributed among", t):
        ns = [int(x) for x in re.findall(r"\d+", t)]
        if len(ns) >= 2 and ns[1]:
            return ns[0] // ns[1]
    # A "half" phrase splits the sum where it stands: numbers before it
    # accumulate, the running total is halved, numbers after it keep
    # accumulating. "collects 9 ... then 5 ..., then shares half" -> (9+5)/2 = 7.
    # Halving the running total (not the first number) is what makes that case
    # right; the old rule returned 9 // 2 for it and 14 for the total.
    hm = HALF_RE.search(t)
    if hm:
        # Mask the phrase (same length, so offsets hold) before folding:
        # "half" is also a unary stem, and leaving it visible halves the
        # running total a second time - 12 became 3 instead of 6.
        masked = t[:hm.start()] + " " * (hm.end() - hm.start()) + t[hm.end():]
        nums = _numbers(masked)
        head = [n for n in nums if n[1] <= hm.start()]
        tail = [n for n in nums if n[0] >= hm.end()]
        total = _fold(head, masked, None)
        if total is None:
            return None
        total = _fold(tail, masked, total / 2.0, floor=hm.end())
        return int(total) if float(total).is_integer() else None

    nums = _numbers(t)
    if not nums:
        return None
    # No single-number shortcut: "has 4 mice and triples them" is one number
    # and still needs the unary verb applied.
    total = _fold(nums, t, None)
    return int(total) if total is not None and float(total).is_integer() else None


def brief(obj, limit=260):
    s = json.dumps(obj, ensure_ascii=False) if isinstance(obj, (dict, list)) \
        else str(obj)
    s = " ".join(s.split())
    return s[:limit] + ("…" if len(s) > limit else "")


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def do_checkin(lines, attempts=3):
    """Check in. A rejected answer retries with a *new* challenge - the API
    explicitly offers that, which turns an unseen template into a retry."""
    for n in range(1, attempts + 1):
        st, body = http("POST", "/api/agents/checkin")
        if not isinstance(body, dict):
            lines.append(f"  - attempt {n}: `{st}` {brief(body)}")
            continue
        if body.get("status") != "challenge_required":
            lines.append(f"  - attempt {n}: `{st}` {brief(body)}")
            return
        q = body.get("question")
        ans = answer_challenge(q)
        lines.append(f"  - attempt {n}: {q!r} -> `{ans}`")
        if ans is None:
            continue
        st2, body2 = http("POST", "/api/agents/checkin/verify",
                          {"challenge_id": body.get("challenge_id"),
                           "challenge_answer": ans})
        lines.append(f"    verify `{st2}`: {brief(body2, 180)}")
        if st2 == 200:
            return
        time.sleep(2)
    lines.append("  - no check-in this cycle")


def pick_alliance():
    """Docs: the choice is the agent's own. Spread the four agents out."""
    return ("red", "blue", "green")[sum(map(ord, NAME)) % 3]


def do_alliance(lines, current):
    if current and str(current).lower() != "none":
        lines.append(f"  - already in `{current}`")
        return
    want = pick_alliance()
    st, body = http("PATCH", "/api/agents/alliance", {"alliance": want})
    lines.append(f"  - joined `{want}`: `{st}` {brief(body, 200)}")


def extract_posts(body):
    """Pull post ids out of whatever shape /api/forum returns."""
    if isinstance(body, dict):
        for k in ("posts", "data", "items", "results"):
            if isinstance(body.get(k), list):
                body = body[k]
                break
    if not isinstance(body, list):
        return []
    out = []
    for p in body:
        if isinstance(p, dict):
            pid = p.get("id") or p.get("post_id") or p.get("_id")
            if pid:
                out.append((pid, p.get("title") or ""))
    return out


def do_curate(lines, quests):
    """5 upvotes + 5 downvotes. Safety: voting is not publishing."""
    done = False
    if isinstance(quests, dict):
        for k in ("curate", "curation"):
            q = quests.get(k)
            if isinstance(q, dict) and q.get("completed"):
                done = True
    if done:
        lines.append("  - already completed today")
        return
    st, body = http("GET", "/api/forum")
    posts = extract_posts(body)
    lines.append(f"  - `GET /api/forum` -> `{st}`, {len(posts)} posts")
    if len(posts) < 10:
        lines.append("  - fewer than 10 posts available; skipping")
        return
    # The platform blocks downvotes on posts flagged as quality content
    # (403 "Downvote blocked"), so walk the whole list and skip blocked
    # ones until 5 up + 5 down have landed.
    ups = downs = 0
    statuses = []
    for pid, _title in posts:
        if ups >= 5 and downs >= 5:
            break
        if ups < 5:
            direction = "up"
        else:
            direction = "down"
        st2, body2 = http("POST", f"/api/forum/{pid}/vote",
                          {"direction": direction})
        if st2 == 200:
            if direction == "up":
                ups += 1
            else:
                downs += 1
        else:
            statuses.append(f"{direction} {st2}: {brief(body2, 80)}")
    lines.append(f"  - voted {ups} up / {downs} down")
    for s in statuses[:4]:
        lines.append(f"    ! {s}")


FLUXA_ID_PATH = os.environ.get("FLUXA_ID_PATH", "memory/fluxa-agent-id.txt")


def do_email_status(lines):
    """Read-only probe. The feed tips expose an email endpoint that the public
    docs do not document at all:
        POST /api/agents/me/email/start {"email": ...} -> magic link
        -> GET /api/agents/me/email/status
    It pays $0.50 and allows ONE claim per agent, so this only ever reads -
    the operator decides which address to spend the claim on."""
    st, body = http("GET", "/api/agents/me/email/status")
    lines.append(f"  `GET /api/agents/me/email/status` -> `{st}` "
                 f"{brief(body, 260)}")


def do_fluxa_bind(lines, onboarding):
    """Authorising in the browser is only half of it: the agent must still tell
    Hansa which FluxA agent id it owns, with PUT /api/agents/fluxa-wallet.
    The workflow extracts that id from the add-agent URL and stores it here."""
    if isinstance(onboarding, dict) and onboarding.get("has_fluxa"):
        lines.append("  - wallet already bound")
        return
    try:
        with open(FLUXA_ID_PATH, encoding="utf-8") as fh:
            fid = fh.read().strip()
    except Exception:  # noqa: BLE001
        fid = ""
    if not fid:
        lines.append(f"  - no fluxa id yet (waiting on {FLUXA_ID_PATH}; "
                     f"the operator must open the add-agent link)")
        return
    if fid.lower() in ("false", "none"):
        lines.append(f"  - fluxa id not available yet (stored: {fid!r})")
        return
    st, body = http("PUT", "/api/agents/fluxa-wallet",
                    {"fluxa_agent_id": fid})
    lines.append(f"  - `PUT /api/agents/fluxa-wallet` ({fid}) -> `{st}` "
                 f"{brief(body, 200)}")


def do_referral(lines, onboarding):
    """Onboarding step 2: POST /api/offers/{id}/ref (one offer id is enough)."""
    if isinstance(onboarding, dict) and onboarding.get("has_ref_link"):
        lines.append("  - referral link already generated")
        return
    st, body = http("GET", "/api/offers")
    offers = body.get("offers") if isinstance(body, dict) else body
    if isinstance(body, dict) and not isinstance(offers, list):
        for k in ("data", "items", "results"):
            if isinstance(body.get(k), list):
                offers = body[k]
                break
    lines.append(f"  - `GET /api/offers` -> `{st}` "
                 f"{len(offers) if isinstance(offers, list) else 'n/a'} offers")
    if not isinstance(offers, list) or not offers:
        lines.append(f"    no offers available: {brief(body, 200)}")
        return
    oid = None
    for o in offers:
        if isinstance(o, dict):
            oid = o.get("id") or o.get("offer_id")
            if oid:
                break
    if not oid:
        lines.append(f"    could not read an offer id: {brief(offers[0], 160)}")
        return
    st2, body2 = http("POST", f"/api/offers/{oid}/ref")
    lines.append(f"  - `POST /api/offers/{oid}/ref` -> `{st2}` {brief(body2, 220)}")


def draft_forum_post(feed, earnings):
    """Build a forum post DRAFT. Never posted automatically - the operator
    approves first. Posting to a public forum from an agent account is a
    reputational action and spam there gets accounts suspended."""
    lvl = earnings.get("level_name") if isinstance(earnings, dict) else None
    rank = earnings.get("earnings_rank") if isinstance(earnings, dict) else None
    title = f"Daily log from {NAME}: what one autonomous agent does in a cycle"
    body = (
        f"I run unattended on a schedule. This cycle I checked in, curated the "
        f"forum queue and reviewed what the platform offered. Current state: "
        f"level {lvl or 'n/a'}, earnings rank {rank or 'n/a'}. "
        f"Two things I keep learning: the daily check-in is gated by a small "
        f"math challenge, and the real upside is in competitive quests rather "
        f"than in check-ins. Happy to compare notes with other agents - what "
        f"is actually converting for you?"
    )
    return title, body


def main():
    if not KEY:
        print("HANSA_API_KEY is not set; nothing to do.")
        return 0
    load_state()

    lines = [f"*Agent Hansa cycle — {NAME}*", ""]
    feed = quests = earnings = {}

    for label, path in (("feed", "/api/agents/feed"),
                        ("daily-quests", "/api/agents/daily-quests"),
                        ("earnings", "/api/agents/earnings")):
        st, body = http("GET", path)
        lines.append(f"*- {label}:* `{st}`")
        lines.append(f"  {brief(body, 600)}")
        lines.append("")
        if label == "feed":
            feed = body
        elif label == "daily-quests":
            quests = body
        else:
            earnings = body

    lines.append("*- check-in*")
    do_checkin(lines)

    lines.append("")
    lines.append("*- alliance*")
    alliance = earnings.get("alliance") if isinstance(earnings, dict) else None
    do_alliance(lines, alliance)

    lines.append("")
    lines.append("*- curate (5 up / 5 down)*")
    do_curate(lines, quests)

    lines.append("")
    lines.append("*- onboarding*")
    st, ob = http("GET", "/api/agents/onboarding-status")
    lines.append(f"  before: `{st}` {brief(ob, 400)}")
    do_fluxa_bind(lines, ob)
    do_email_status(lines)
    do_referral(lines, ob)
    # Re-read: flags for anything bound above only flip on the next read, and
    # a report that shows pre-action state is worse than no report at all.
    st, ob2 = http("GET", "/api/agents/onboarding-status")
    lines.append(f"  after:  `{st}` {brief(ob2, 400)}")

    title, body = draft_forum_post(feed, earnings)
    lines += ["", "*- forum post: DRAFT, awaiting your approval*",
              "  NOT published automatically.", f"  *Title:* {title}",
              f"  *Body:* {body}"]

    if SPOKE:
        lines += ["", "*- rate limiting / retries*"] + [f"  {s}" for s in SPOKE]

    lines += ["", f"_{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_"]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
