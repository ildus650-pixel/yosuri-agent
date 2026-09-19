#!/usr/bin/env python3
"""Turn the rescene CLI's terminal UI stream into plain text.

The CLI renders boxes, colours and a rotating "thinking" spinner written with
carriage returns. In CI stdout is not a TTY, so the whole animated stream lands
in the log verbatim. This strips the chrome and keeps the actual answer.

Usage: clean_output.py <raw-file>   -> cleaned text on stdout
"""
import re
import sys

OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Rotating spinner frames the CLI rewrites in place.
SPINNER = re.compile(r"^\s*(?:🤔|⏳|\.)*\s*思考中[.．]*\s*$")

# Box-drawing chrome.
LEAD = re.compile(r"^[\s┌└├│╭╰]+")
TAIL = re.compile(r"[\s│┐┘┤╮╯]+$")
RULE = re.compile(r"─{2,}")


def clean(raw: str) -> str:
    raw = OSC.sub("", raw)
    raw = ANSI.sub("", raw)

    out = []
    for line in raw.split("\n"):
        # On a real TTY only the text after the last \r is visible.
        if "\r" in line:
            line = line.split("\r")[-1]

        line = LEAD.sub("", line)
        line = TAIL.sub("", line)
        line = RULE.sub("", line).strip()

        if not line or SPINNER.match(line):
            if out and out[-1] == "":
                continue
            out.append("")
        else:
            out.append(line)

    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: clean_output.py <raw-file>", file=sys.stderr)
        return 2
    try:
        raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        print("(no output file — the agent produced nothing)", file=sys.stderr)
        return 0
    sys.stdout.write(clean(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
