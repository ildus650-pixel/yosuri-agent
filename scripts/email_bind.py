#!/usr/bin/env python3
"""Claim Agent Hansa's verified-email bonus ($0.50, one claim per agent).

The endpoint is NOT in the public documentation - it is advertised by the live
feed, which is why reading the docs alone makes it look as if no email binding
exists:

    POST /api/agents/me/email/start {"email": "..."}   -> sends a magic link
    <click the magic link>
    GET  /api/agents/me/email/status                   -> connected / bonus

An agent has no inbox of its own, so this creates a throwaway mailbox, waits
for the link, clicks it, and re-reads the status. Set EMAIL_OVERRIDE to a real
address instead - then the magic link is printed for the operator to click.

Refuses to run when the status already reports the bonus as paid, because the
claim cannot be repeated.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("HANSA_BASE", "https://www.agenthansa.com")
KEY = os.environ.get("HANSA_API_KEY", "").strip()
NAME = os.environ.get("AGENT_NAME", "agent")
OVERRIDE = os.environ.get("EMAIL_OVERRIDE", "").strip()
MAILTM = "https://api.mail.tm"
UA = "hansa-email-bind/1.0"
PASSWORD = "Hansa!" + os.urandom(6).hex()

_last = 0.0


def pace(min_interval=2.0):
    global _last
    wait = min_interval - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()


def call(method, url, body=None, headers=None, timeout=45):
    """Return (status, parsed). Never raises."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, _json(raw)
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _json(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"_text": raw[:500]}


def hansa(method, path, body=None):
    pace()
    return call(method, BASE + path, body,
                {"Authorization": "Bearer " + KEY})


def short(obj, n=300):
    s = json.dumps(obj, ensure_ascii=False) if isinstance(obj, (dict, list)) \
        else str(obj)
    return " ".join(s.split())[:n]


def make_mailbox():
    """Create a throwaway mail.tm mailbox. Returns (address, token) or (None, None)."""
    st, dom = call("GET", MAILTM + "/domains")
    # mail.tm answers with a hydra collection, but has served a bare list too
    domains = dom if isinstance(dom, list) else (dom or {}).get("hydra:member")
    if not domains:
        return None, None, f"mail.tm domains -> {st} {short(dom, 120)}"
    domain = domains[0].get("domain") if isinstance(domains[0], dict) else None
    if not domain:
        return None, None, f"no usable domain in {short(domains[0], 120)}"
    address = f"{NAME}-{int(time.time())}@{domain}".lower()
    st, acc = call("POST", MAILTM + "/accounts",
                   {"address": address, "password": PASSWORD})
    if st not in (200, 201):
        return None, None, f"create -> {st} {short(acc, 160)}"
    st, tok = call("POST", MAILTM + "/token",
                   {"address": address, "password": PASSWORD})
    if st != 200 or "token" not in (tok or {}):
        return None, None, f"token -> {st} {short(tok, 160)}"
    return address, tok["token"], None


def find_link(token, attempts=18, every=5):
    """Poll the mailbox for the magic link."""
    for i in range(attempts):
        time.sleep(every)
        st, msgs = call("GET", MAILTM + "/messages", None,
                        {"Authorization": "Bearer " + token})
        items = (msgs or {}).get("hydra:member") or []
        if items:
            mid = items[0].get("id")
            st2, full = call("GET", f"{MAILTM}/messages/{mid}", None,
                             {"Authorization": "Bearer " + token})
            blob = " ".join(str(v) for v in (full or {}).values())
            for m in re.finditer(r"https?://[^\s\"'<>)]+", blob):
                u = m.group().replace("&amp;", "&").rstrip(".")
                if "agenthansa" in u or "magic" in u or "verify" in u:
                    return u, f"link found after {(i + 1) * every}s"
            return None, f"message arrived but held no link: {short(full, 200)}"
    return None, f"no mail within {attempts * every}s"


def main():
    if not KEY:
        print("HANSA_API_KEY is not set; nothing to do.")
        return 0

    out = [f"*- Email bonus — {NAME}*"]

    st, before = hansa("GET", "/api/agents/me/email/status")
    out.append(f"  before: `{st}` {short(before, 260)}")
    if not isinstance(before, dict):
        print("\n".join(out))
        return 0
    if before.get("bonus_already_paid") or before.get("connected"):
        out.append("  - claim already used; not repeating")
        print("\n".join(out))
        return 0

    if OVERRIDE:
        address, why = OVERRIDE, "operator-supplied address"
    else:
        address, token, why = make_mailbox()
        if not address:
            out.append(f"  mailbox unavailable: {why}")
            print("\n".join(out))
            return 0
    out.append(f"  address: `{address}` ({why})")

    st, started = hansa("POST", "/api/agents/me/email/start",
                        {"email": address})
    out.append(f"  `POST /api/agents/me/email/start` -> `{st}` "
               f"{short(started, 240)}")
    if st not in (200, 201, 202):
        print("\n".join(out))
        return 0

    if OVERRIDE:
        out.append("  - magic link sent to the operator's address; click it, "
                   "then re-read the status")
    else:
        link, why = find_link(token)
        out.append(f"  {why}")
        if link:
            st, clicked = call("GET", link)
            out.append(f"  clicked: `{st}` {short(clicked, 160)}")

    time.sleep(3)
    st, after = hansa("GET", "/api/agents/me/email/status")
    out.append(f"  after: `{st}` {short(after, 300)}")
    if isinstance(after, dict) and after.get("bonus_already_paid"):
        out.append("  RESULT: $0.50 bonus claimed")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
