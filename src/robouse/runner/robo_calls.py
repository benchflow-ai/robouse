"""The `robo` commands an agent wrote in a shell command line, read as the shell and robo would read them.

Used to check which of an episode's requests a tool call could have sent (runner/atif.py places each request in the
call that was running when the episode server got it, and checks the placement against the call's commands):

- the line is split into simple commands at `;`, `&&`, `||`, `|`, `&`, newlines and parentheses, outside quotes;
  `$(...)` and backticks open a command substitution; a loop's body is what lies between its `do` and `done`;
- a `robo` command with literal arguments sends the request robo's own parser builds from them
  (`agent_cli.build_request`); one in a loop's body or with shell variables sends requests of its kind, any number;
- a line that runs a script or a program of the agent's (an interpreter, or a program by its path such as
  /tmp/s.sh), or feeds a heredoc to one, can send any request.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

from ..agent_cli import HELP_FLAGS, build_request

LOOP_OPEN = frozenset({"for", "while", "until", "select"})
KEYWORDS = frozenset({"then", "else", "elif", "if", "fi", "!", "time", "{", "}", "in", "esac", "case"})
WRAPPERS = frozenset({"nice", "timeout", "exec", "command", "env"})
REDIR_ALONE = re.compile(r"^(\d*>>?|\d*<|&>>?|\d*>&|\d*<&)$")  # an operator alone: its target is the next word
REDIR_FULL = re.compile(r"^(\d*>>?|\d*<|&>>?)\S+$|^\d*[<>]&\d*-?$")  # an operator with its target
INTERPRETER = re.compile(r"^(python\d?(\.\d+)?|bash|sh|zsh|dash|node|perl|ruby|source|\.|xargs)$")
OPS = {"move-to": "move_to", "give-up": "give_up"}


@dataclass(frozen=True)
class RoboCommand:
    text: str  # as written, one simple command
    op: str  # the request's op: info, observe, act, move_to, grip, skill, done, give_up
    req: dict[str, Any] | None  # the request it sends, when its arguments are literal
    loop: bool  # in a loop's body: it may send any number of requests


def simple_commands(text: str) -> list[tuple[str, int, bool]]:
    """(command, loop depth, inside a command substitution) for each simple command of a shell line."""
    out: list[tuple[str, int, bool]] = []
    buf: list[str] = []
    depth = 0
    subst = 0
    quote = ""
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal depth
        s = "".join(buf).strip()
        buf.clear()
        words = s.split()
        while words:
            w = words[0]
            if w in LOOP_OPEN:  # a loop's header; `while robo ...` runs robo as the condition
                s = " ".join(words[1:]) if w in ("while", "until") else ""
                break
            if w == "do":
                depth += 1
            elif w == "done":
                depth = max(0, depth - 1)
            elif w not in KEYWORDS:
                break
            words = words[1:]
            s = " ".join(words)
        if s.strip():
            out.append((s.strip(), depth, subst > 0))

    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "\\" and i + 1 < n:
            buf.append(text[i : i + 2])
            i += 2
            continue
        elif text.startswith("$(", i):
            flush()
            subst += 1
            i += 2
            continue
        elif ch == ")" and subst:
            flush()
            subst -= 1
            i += 1
            continue
        elif ch == "`":
            flush()
            subst = 0 if subst else 1
            i += 1
            continue
        elif ch == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif ch == "&" and ((i > 0 and text[i - 1] in "<>") or text.startswith(">", i + 1)):
            pass  # a redirection (2>&1, &>), not a separator
        elif ch in ";\n&|()":
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return out


def robo_commands(text: str) -> list[RoboCommand]:
    """The `robo` commands written in a shell line, in order; a command that sends nothing (help, bad arguments) is
    left out."""
    found: list[RoboCommand] = []
    for s, depth, in_subst in simple_commands(text):
        words = _words(s)
        if not words or not (words[0] == "robo" or words[0].endswith("/robo")):
            continue
        args: list[str] = []
        k = 1
        while k < len(words):
            if REDIR_FULL.match(words[k]):
                k += 1
            elif REDIR_ALONE.match(words[k]):
                k += 2
            else:
                args.append(words[k])
                k += 1
        args = [x for x in args if x != "--json"]
        if not args or args[0] == "help" or any(x in HELP_FLAGS for x in args):
            continue
        req: dict[str, Any] | None = None
        if "$" not in s and "`" not in s and not in_subst:
            try:
                req = build_request(args[0], args[1:])
            except (ValueError, IndexError, KeyError):
                continue
        found.append(RoboCommand(s, OPS.get(args[0], args[0]), req, depth > 0))
    return found


def _words(s: str) -> list[str]:
    try:
        words = shlex.split(s, posix=True)
    except ValueError:
        words = s.split()
    while words and re.fullmatch(r"[A-Za-z_]\w*=.*", words[0]):  # VAR=value prefixes
        words = words[1:]
    if words and words[0] in WRAPPERS:
        words = [w for w in words[1:] if not re.fullmatch(r"-\S*|\d+[smh]?", w)]
    return words


def runs_programs(command: str) -> bool:
    """Whether a shell line runs a script or a program that may call robo itself: an interpreter (python, bash, ...),
    or a program by its path (./run.sh, /tmp/s.sh); a heredoc fed to one counts too."""
    for s, _, _ in simple_commands(command):
        words = _words(s)
        if not words:
            continue
        name = words[0].split("/")[-1]
        if INTERPRETER.match(name) or ("/" in words[0] and name != "robo"):
            return True
    return "<<" in command


def unexplained(command: str, requests: list[dict[str, Any]]) -> int:
    """How many of `requests` (in the order the episode server got them) no `robo` command of `command` could have
    sent: literal commands match their own request in order (one that sent nothing, after an error, is passed over);
    a command in a loop's body or with variables matches requests of its kind; a script matches anything."""
    cmds = robo_commands(command)
    static = [c for c in cmds if c.req is not None and not c.loop]
    loose = {c.op for c in cmds if c.req is None or c.loop}
    anything = runs_programs(command)

    def same(req: dict[str, Any], want: dict[str, Any]) -> bool:
        return all(req.get(k) == v for k, v in want.items())

    k = bad = 0
    for req in requests:
        if k < len(static) and same(req, static[k].req or {}):
            k += 1
            continue
        later = next((q for q in range(k + 1, len(static)) if same(req, static[q].req or {})), None)
        if later is not None and req.get("op") not in loose:
            k = later + 1
            continue
        if anything or req.get("op") in loose:
            continue
        bad += 1
    return bad
