#!/usr/bin/env python3
"""Post a file's contents to Telegram, chunked to Telegram's message limit.

Usage: notify.py <file> [title]
Env:   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import sys
import urllib.parse
import urllib.request

LIMIT = 3900  # Telegram hard limit is 4096; leave headroom for the chunk header.


def chunks(text: str, limit: int = LIMIT):
    """Split on line boundaries so messages stay readable."""
    buf, size = [], 0
    for line in text.splitlines():
        add = len(line) + 1
        if size + add > limit and buf:
            yield "\n".join(buf)
            buf, size = [], 0
        buf.append(line)
        size += add
    if buf:
        yield "\n".join(buf)


def send(token: str, chat: str, text: str) -> bool:
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
            return bool(body.get("ok"))
    except Exception as exc:  # noqa: BLE001 - surface the reason, never crash the job
        print(f"telegram send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: notify.py <file> [title]", file=sys.stderr)
        return 2
    title = sys.argv[2] if len(sys.argv) > 2 else "Yosuri Agent"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("telegram secrets missing", file=sys.stderr)
        return 0

    try:
        body = open(sys.argv[1], encoding="utf-8", errors="replace").read().strip()
    except FileNotFoundError:
        body = ""
    if not body:
        body = "(agent produced no output)"

    parts = list(chunks(body)) or [body]
    ok = 0
    for i, part in enumerate(parts, 1):
        prefix = f"{title}\n\n" if len(parts) == 1 else f"{title} ({i}/{len(parts)})\n\n"
        if send(token, chat, prefix + part):
            ok += 1
    print(f"delivered {ok}/{len(parts)} message(s)")
    return 0 if ok == len(parts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
