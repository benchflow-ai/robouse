#!/usr/bin/env python3
"""Build the static Robo Use docs site (robouse.ai/docs/) from docs/.

    python tools/docs/build_docs.py --out <site checkout>/site/docs
    python tools/docs/build_docs.py --out /tmp/docs --base /docs/     # --base is the URL prefix the pages are served under

Standard library only (Python 3.11+): it has its own small markdown converter that covers what these docs use
(headings, paragraphs, nested lists, fenced code, tables, block quotes, links, images, emphasis, inline code).

Output: one page per doc at <out>/<slug>/index.html (pretty URLs), plus docs.css and docs.js. Every page uses the
site's shared header and footer from the site repository's tools/chrome.py (found next to --out, or --chrome) and
expects /theme.js, /surface.css, /bridge.css, /chrome.css, /prose.css (the site's one type system) and /fonts/ at the site root.

Only the pages in PAGES are published. Links between them are rewritten to the generated pages (anchors kept);
links to repository files that are not published become plain text or inline code, so that every link on the
site leads to a published page; site links starting with "/" are kept. The build fails if a link between pages is
broken, or if the output contains a banned word or anything that looks like a credential (see check_output).

Sources are read from git HEAD by default (--ref REV for another revision, --worktree for uncommitted edits), so
the site matches the repository.
"""

from __future__ import annotations

import argparse
import codecs
import html
import importlib.util
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GITHUB = "https://github.com/benchflow-ai/robouse"
# Absolute links to docs in the repository (README uses them so they work on PyPI) map to the generated pages.
GITHUB_DOC_RE = re.compile(re.escape(GITHUB) + r"/(?:blob|tree)/main/((?:docs/|README\.md).*)$")
MARKER = ".build_docs"  # written into --out so a rebuild only ever clears a directory this script owns
# The social card, from the hub and runs pages' template (tools/build_hub.py og_card, tools/site/build_runs_site.py
# page): the site's card, since a docs page has no picture of its own, and the page's own description (PAGES).
CARD = "https://robouse.ai/og/landing.png?v=7"


WRAP_AT = 56  # long robouse and bench commands go one flag per line beyond this many characters
WRAP_CMD = re.compile(r"^(\$ )?(robouse (run|run-many|tasks init|report)|bench eval run)\s")
LONG_WORD = 28  # inline code this short never breaks; longer code breaks between words, and a long word after a slash


def code_html(text: str) -> str:
    """Inline code that never splits a flag or an id ("--" / "grip", "gpt-6-" / "astra").

    Code up to LONG_WORD characters is plain <code>, which docs.css keeps on one line. Longer code is .brk: it wraps
    between its words, each word a .w span that stays whole, and a word longer than LONG_WORD may also break after each
    slash; a long word without a slash, or a part between slashes longer than LONG_WORD, breaks after its "--"
    separators (an id such as put-in-container--franka-panda--tabletop--s0), or else where the line needs it, rather
    than run past a phone's column.
    """

    def esc(s: str) -> str:
        return html.escape(s, quote=False)

    if len(text) <= LONG_WORD:
        return f"<code>{esc(text)}</code>"
    words: list[str] = []  # an optional part in brackets ("[--camera C]") stays one word
    for w in text.split(" "):
        if words and words[-1].count("[") > words[-1].count("]"):
            words[-1] += " " + w
        else:
            words.append(w)

    def long(w: str) -> str:
        """A part longer than LONG_WORD: whole between its "--" separators if it has them, else free to break."""
        chunks = [c for c in re.split(r"(?<=--)", w) if c]
        if len(chunks) > 1 and all(len(c) <= LONG_WORD for c in chunks):
            return "<wbr>".join(f'<span class="w">{esc(c)}</span>' for c in chunks)
        return esc(w)

    def word(w: str) -> str:
        if not w:
            return ""
        if len(w) <= LONG_WORD:
            return f'<span class="w">{esc(w)}</span>'
        if "/" in w:
            return "<wbr>".join(
                f'<span class="w">{esc(p)}</span>' if len(p) <= LONG_WORD else long(p)
                for p in re.split(r"(?<=/)", w)
                if p
            )
        return long(w)

    return '<code class="brk">' + " ".join(word(w) for w in words) + "</code>"


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of a PNG, JPEG or WebP file, from its header; None if it is none of those."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8 ":
            return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
        if kind == b"VP8L":
            b = int.from_bytes(data[21:25], "little")
            return 1 + (b & 0x3FFF), 1 + ((b >> 14) & 0x3FFF)
        return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    return None


def wrap_command(line: str) -> list[str]:
    """Put a long robouse/bench command on one flag per line, with backslash continuations.

    Only simple commands are touched: no pipes, chains, comments, redirects or existing continuations.
    """
    if len(line) <= WRAP_AT or not WRAP_CMD.match(line) or re.search(r"&&|\|\||[|;<>#]|\\$", line):
        return [line]
    prompt = "$ " if line.startswith("$ ") else ""
    lex = shlex.shlex(line[len(prompt) :], posix=False)
    lex.whitespace_split, lex.commenters = True, ""
    toks = list(lex)
    first = next((i for i, t in enumerate(toks) if t.startswith("-")), None)
    if first is None:
        return [line]
    groups, cur = [" ".join(toks[:first])], []
    for t in toks[first:]:
        if t.startswith("-") or len(cur) >= 2:  # a flag and at most one value per line
            if cur:
                groups.append(" ".join(cur))
            cur = [t]
        else:
            cur.append(t)
    groups.append(" ".join(cur))
    ind = " " * (len(prompt) + 2)
    return [prompt + groups[0] + " \\"] + [ind + g + " \\" for g in groups[1:-1]] + [ind + groups[-1]]


class Source:
    """Reads docs from a git revision (default HEAD, so the site matches the repository) or the working tree."""

    def __init__(self, ref: str | None):
        self.ref = ref
        if ref:
            out = subprocess.run(
                ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", ref],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.paths = set(out.splitlines())
        else:
            self.paths = {str(f.relative_to(REPO)) for f in REPO.rglob("*") if f.is_file() and ".git" not in f.parts}

    def exists(self, path: str) -> bool:
        return path in self.paths

    def list(self, folder: str, suffix: str) -> list[str]:
        return sorted(q for q in self.paths if posixpath.dirname(q) == folder.rstrip("/") and q.endswith(suffix))

    def read_bytes(self, path: str) -> bytes:
        if self.ref:
            return subprocess.run(
                ["git", "-C", str(REPO), "show", f"{self.ref}:{path}"], check=True, capture_output=True
            ).stdout
        return (REPO / path).read_bytes()

    def read(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")


# (group, source path relative to the repo, slug, nav label, meta description). Order = sidebar order = prev/next
# order. The description is one sentence under 155 characters with a fact specific to the page.
# Old slug -> new "slug#anchor" of pages that were merged or renamed; a redirect stub is written at the old URL.
REDIRECTS = {
    "tasks": "concepts#tasks-and-scoring",
    "episodes": "concepts#episodes-and-robo",
    "harnesses": "concepts#harnesses",
    "run-an-agent": "run-agents",
    "datasets": "run-a-suite#a-dataset",
    "robo-cli": "cli#robo",
    "remix": "write-a-task#compose-a-task",
    "components": "concepts#components",
}
PAGES: list[tuple[str, str, str, str, str]] = [
    (
        "Get started",
        "docs/index.md",
        "",
        "Overview",
        "Robo Use turns robot benchmarks into tasks that an agent harness such as Claude Code solves by driving a simulated robot with robo.",
    ),
    (
        "Get started",
        "docs/quickstart.md",
        "quickstart",
        "Quickstart",
        "Install robouse and let Claude Code solve arc-gravity, a rule-inference task on a table, in 35 robo calls.",
    ),
    (
        "Get started",
        "docs/supported.md",
        "supported",
        "Supported",
        "The models, harnesses, platforms, isolation modes and formats Robo Use 0.6.1 supports, and what each needs.",
    ),
    (
        "Get started",
        "docs/concepts.md",
        "concepts",
        "Concepts",
        "Tasks, scoring, episodes, the robo command, harnesses and the trial folder: how one Robo Use trial works.",
    ),
    (
        "Guides",
        "docs/run-agents.md",
        "run-agents",
        "Run agents and VLAs",
        "Run Claude Code, Codex, Gemini CLI, mini-swe-agent, dimcode, Kinex, ASPIRE, Show-Harness, Dream-1, Jev or a VLA policy server as the robot's policy.",
    ),
    (
        "Guides",
        "docs/mcp.md",
        "mcp",
        "MCP",
        "Drive the robot through the robo MCP tools instead of the robo command: the tools, robo mcp and --interface.",
    ),
    (
        "Guides",
        "docs/write-a-task.md",
        "write-a-task",
        "Write or compose a task",
        "Copy a tabletop task, change its goal, and check that its reference solution scores 1 and the no-op control 0.",
    ),
    (
        "Guides",
        "docs/run-a-suite.md",
        "run-a-suite",
        "Run a suite or dataset",
        "Run many tasks with robouse run-many, or a published dataset in Docker with bench eval run -d.",
    ),
    (
        "Guides",
        "docs/flora.md",
        "flora",
        "Annotate trials with Flora",
        "Label trial recordings with NVIDIA's open Flora models, and see how often Flora's verdict agrees with the simulator's.",
    ),
    (
        "Reference",
        "docs/cli.md",
        "cli",
        "CLIs",
        "The --help output of every robouse command and of robo, the agent's only way to act.",
    ),
    (
        "Reference",
        "docs/task-format.md",
        "task-format",
        "task.md",
        "The fields of a Robo Use task.md: BenchFlow's task fields and the robouse block, with defaults.",
    ),
    (
        "Reference",
        "docs/suites.md",
        "suites",
        "Suites",
        "Every suite in the robouse package, with its task count, what it needs and its reference-solution and no-op results.",
    ),
    (
        "Reference",
        "docs/configuration.md",
        "configuration",
        "Configuration",
        "The ROBOUSE_* environment variables you can set: cache and asset paths, the sandbox, simulator virtualenvs and policy servers.",
    ),
    (
        "Reference",
        "docs/metrics.md",
        "metrics",
        "Metrics",
        "Episode metrics from the physical trace, placement splits, and robouse report with 95% intervals.",
    ),
]
# Docs kept in the repository but not published: internal notes, run logs and machine-specific setup.
EXCLUDED = {
    "docs/components.md": "maintainers' notes on components; the public part is in concepts.md and write-a-task.md",
    "docs/components-design.md": "design of components",
    "docs/remix.md": "replaced by the compose sections of concepts.md and write-a-task.md",
    "docs/audit.md": "the maintainers' audit script over local runs",
    "docs/viewer.md": "the viewer formats and the maintainers' viewer tools",
    "docs/benchflow.md": "maintainers' notes on the BenchFlow engine",
    "docs/molmoact2.md": "GPU server setup notes",
    "docs/real-robots.md": "the real suite is not in the package",
    "docs/vla.md": "maintainers' VLA notes and GPU results; the public part is in run-agents.md",
    "docs/suites/": "per-suite design notes; the public part is suites.md",
}
# Build-time guard: none of these may appear in the output. Stored rot13-encoded so the word itself never
# appears in the repository either.
BANNED_WORDS = [codecs.decode(w, "rot13") for w in ["uneobe"]]
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{16,}",
    r"sk-ant-[A-Za-z0-9_-]+",
    r"pypi-[A-Za-z0-9_-]{16,}",
    r"npm_[A-Za-z0-9]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"hf_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"(?i)(?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
]


# ---------------------------------------------------------------------------------------------------------------
# markdown -> html


def slugify(text: str, seen: dict[str, int]) -> str:
    """GitHub-style heading id: lowercase, drop punctuation, spaces to hyphens, -1/-2 for duplicates."""
    s = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def plain(md: str) -> str:
    """Rough markdown -> plain text, for heading ids, titles and descriptions."""
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", md)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"`+([^`]*)`+", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", s)
    return s.strip()


class Converter:
    """Converts one markdown document. `link` maps (href) -> (url or None); None means 'not published'."""

    def __init__(self, link, labels=None, svg=None, size=None):
        self.link = link
        self.svg = svg  # href -> inline SVG markup (or None), for figures that follow the page's theme
        self.size = size  # href -> (width, height) of an image file (or None), so <img> carries its size
        self.labels = labels or {}  # page url -> nav label, for links whose text is just the file path
        self.seen: dict[str, int] = {}
        self.headings: list[tuple[int, str, str]] = []

    # ---- inline

    def inline(self, text: str) -> str:
        slots: list[str] = []

        def keep(h: str) -> str:
            slots.append(h)
            return f"\x00{len(slots) - 1}\x00"

        # code spans (any run of backticks), then <autolinks>
        text = re.sub(
            r"(`+)(.+?)\1", lambda m: keep(code_html(m.group(2).strip() if m.group(1) != '`' else m.group(2))), text
        )
        text = re.sub(r"<(https?://[^>\s]+)>", lambda m: keep(self._a(m.group(1), html.escape(m.group(1)))), text)
        text = html.escape(text, quote=False)
        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", lambda m: keep(self._img(m.group(2), m.group(1))), text)
        text = re.sub(
            r'\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)(?:\s+"[^)]*")?\)',
            lambda m: keep(self._link(m.group(2), self.emph(m.group(1)))),
            text,
        )
        text = re.sub(
            r"(?<![\w/\"'=])(https?://[^\s<>()\]]*[^\s<>()\].,;:!?'\"])",
            lambda m: keep(self._a(m.group(1), m.group(1))),
            text,
        )
        text = self.emph(text)
        text = re.sub(r"  $", "<br>", text)
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)
        return text

    @staticmethod
    def emph(s: str) -> str:
        s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", s)
        return s

    @staticmethod
    def _a(href: str, inner: str) -> str:
        return f'<a href="{html.escape(href)}">{inner}</a>'

    def _link(self, href: str, inner: str) -> str:
        href = html.unescape(href)
        if re.match(r"^(https?:|mailto:)", href) and not GITHUB_DOC_RE.match(href):
            return self._a(href, inner)
        url = self.link(href)
        if url:
            text = html.unescape(re.sub(r"<[^>]+>", "", inner))
            if "\x00" not in inner and re.fullmatch(r"[\w./\-]+\.md(#[\w\-]*)?|(docs/)?suites/", text):
                inner = html.escape(self.labels.get(url.split("#")[0], text), quote=False)
            return self._a(url, inner)
        # not published: keep the words; a bare path becomes inline code
        text = re.sub(r"<[^>]+>", "", inner)
        if "\x00" in inner or "<code" in inner or not re.fullmatch(r"[\w./#\-]+", html.unescape(text)):
            return inner
        return code_html(html.unescape(text))

    def _img(self, src: str, alt: str) -> str:
        src = html.unescape(src)
        url = src if re.match(r"^https?:", src) else self.link(src)
        if not url:
            return alt
        size = self.size(src) if self.size and not re.match(r"^https?:", src) else None
        dims = f' width="{size[0]}" height="{size[1]}"' if size else ""  # the page keeps its layout while images load
        return f'<img src="{html.escape(url)}" alt="{alt}"{dims} loading="lazy">'

    # ---- blocks

    LIST_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)")
    FENCE_RE = re.compile(r"^( *)(`{3,}|~{3,})\s*([\w+-]*)")
    HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
    SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

    def starts_block(self, line: str, lines: list[str], i: int) -> bool:
        return bool(
            self.FENCE_RE.match(line)
            or self.HEAD_RE.match(line)
            or line.startswith(">")
            or self.LIST_RE.match(line)
            or re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line)
            or (line.lstrip().startswith("|") and i + 1 < len(lines) and self.SEP_RE.match(lines[i + 1]))
        )

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = self.FENCE_RE.match(line)
            if m:
                ind, fence, lang = len(m.group(1)), m.group(2), m.group(3)
                body, i = [], i + 1
                while i < n and not (
                    lines[i].strip().startswith(fence[0] * len(fence)) and not lines[i].strip().strip(fence[0])
                ):
                    body.append(lines[i][ind:] if lines[i][:ind].strip() == "" else lines[i])
                    i += 1
                i += 1
                if lang == "gallery":  # one "image | caption" per line: a strip of small figures
                    items = []
                    for row in body:
                        if "|" not in row:
                            continue
                        src, cap = (s.strip() for s in row.split("|", 1))
                        items.append(
                            f"<figure>{self._img(src, plain(cap))}<figcaption>{self.inline(cap)}</figcaption></figure>"
                        )
                    out.append('<div class="gallery">' + "".join(items) + "</div>")
                    continue
                cls = f' class="language-{lang}"' if lang else ""
                if lang in ("console", "sh", "bash"):
                    body = [w for row in body for w in wrap_command(row)]
                out.append(
                    f'<div class="code"><pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre></div>'
                )
                continue
            m = self.HEAD_RE.match(line)
            if m:
                level, text = len(m.group(1)), m.group(2)
                hid = slugify(plain(text), self.seen)
                self.headings.append((level, hid, text))
                inner = self.inline(text)
                if level == 1:
                    out.append(f"<h1 id=\"{hid}\">{inner}</h1>")
                else:  # the section link sits beside the heading, not in it, so the heading's name is just its text
                    cmd = ' class="cmd"' if re.fullmatch(r"`[^`]+`", text) else ""  # a heading that is one command
                    out.append(
                        f'<div class="hd hd{level}"><h{level} id="{hid}"{cmd}>{inner}</h{level}>'
                        f'<a class="hash" href="#{hid}" aria-label="Link to {html.escape(plain(text))}"></a></div>'
                    )
                i += 1
                continue
            if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
                out.append("<hr>")
                i += 1
                continue
            if line.lstrip().startswith("|") and i + 1 < n and self.SEP_RE.match(lines[i + 1]):
                rows = [line]
                sep = lines[i + 1]
                i += 2
                while i < n and lines[i].lstrip().startswith("|"):
                    rows.append(lines[i])
                    i += 1
                out.append(self.table(rows[0], sep, rows[1:]))
                continue
            if line.startswith(">"):
                body = []
                while i < n and lines[i].strip() and lines[i].startswith(">"):
                    body.append(re.sub(r"^> ?", "", lines[i]))
                    i += 1
                out.append(f"<blockquote>{self.blocks(body)}</blockquote>")
                continue
            if self.LIST_RE.match(line):
                i = self.list_block(lines, i, out)
                continue
            fm = re.fullmatch(r"!\[([^\]]+)\]\(([^)\s]+)\)", line.strip())
            if fm and (i + 1 >= n or not lines[i + 1].strip()):  # an image alone in its paragraph: a figure
                cap, src = fm.group(1), fm.group(2)
                svg = self.svg(src) if self.svg and src.endswith(".svg") else None
                body = (
                    svg.replace("<svg ", f'<svg role="img" aria-label="{html.escape(plain(cap))}" ')
                    if svg
                    else self._img(src, html.escape(plain(cap)))
                )
                cls = "figure has-narrow" if svg and "fig-narrow" in svg else "figure"
                out.append(f'<figure class="{cls}">{body}<figcaption>{self.inline(cap)}</figcaption></figure>')
                i += 1
                continue
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not self.starts_block(lines[i], lines, i):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.inline(chr(10).join(para))}</p>")
        return "\n".join(out)

    def list_block(self, lines: list[str], i: int, out: list[str]) -> int:
        n = len(lines)
        m = self.LIST_RE.match(lines[i])
        base = len(m.group(1))
        ordered = m.group(2)[0].isdigit()
        start = int(m.group(2)[:-1]) if ordered else 1
        items: list[list[str]] = []
        loose = False
        while i < n:
            m = self.LIST_RE.match(lines[i])
            if not m or len(m.group(1)) != base or m.group(2)[0].isdigit() != ordered:
                break
            content_ind = len(m.group(0)) if m.group(3) else len(m.group(0)) + 1
            item = [lines[i][len(m.group(0)) :]]
            i += 1
            while i < n:
                ln = lines[i]
                if not ln.strip():
                    # blank: the item continues only if the next non-blank line is indented under it
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if (
                        j < n
                        and len(lines[j]) - len(lines[j].lstrip()) > base
                        and not (self.LIST_RE.match(lines[j]) and len(self.LIST_RE.match(lines[j]).group(1)) == base)
                    ):
                        item.extend([""] * (j - i))
                        i = j
                        loose = loose or not self.LIST_RE.match(lines[j])
                        continue
                    break
                indent = len(ln) - len(ln.lstrip())
                lm = self.LIST_RE.match(ln)
                if indent > base:
                    item.append(ln[min(indent, content_ind) :])
                elif lm or self.starts_block(ln, lines, i):
                    break
                else:
                    item.append(ln.strip())  # lazy continuation of the item's paragraph
                i += 1
            items.append(item)
            # blank lines between items make the list loose
            j = i
            while j < n and not lines[j].strip():
                j += 1
            nm = self.LIST_RE.match(lines[j]) if j < n else None
            if j > i and nm and len(nm.group(1)) == base and nm.group(2)[0].isdigit() == ordered:
                loose = True
                i = j
        tag = "ol" if ordered else "ul"
        attr = f' start="{start}"' if ordered and start != 1 else ""
        lis = []
        for item in items:
            body = self.blocks(item)
            if not loose:
                body = re.sub(r"^<p>(.*?)</p>", r"\1", body, count=1, flags=re.S)
            lis.append(f"<li>{body}</li>")
        out.append(f"<{tag}{attr}>\n" + "\n".join(lis) + f"\n</{tag}>")
        return i

    def table(self, head: str, sep: str, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            row = row.strip()
            row = row[1:] if row.startswith("|") else row
            row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
            parts, cur, in_code = [], "", False
            k = 0
            while k < len(row):
                c = row[k]
                if c == "\\" and k + 1 < len(row) and row[k + 1] == "|":
                    cur += "|"
                    k += 2
                    continue
                if c == "`":
                    in_code = not in_code
                if c == "|" and not in_code:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += c
                k += 1
            parts.append(cur)
            return [p.strip() for p in parts]

        aligns = []
        for s in cells(sep):
            aligns.append(
                "center"
                if s.startswith(":") and s.endswith(":")
                else "right"
                if s.endswith(":")
                else "left"
                if s.startswith(":")
                else ""
            )
        heads = cells(head)
        ncol = len(heads)
        labels = [plain(h) for h in heads]

        def cell(c: str) -> str:
            # "first<br>second": the second line is a quieter note under the first (a suite's description under its id)
            first, *rest = c.split("<br>")
            return self.inline(first) + "".join(f'<span class="sub">{self.inline(x)}</span>' for x in rest)

        def row_html(r: list[str], tag: str) -> str:
            tds = []
            for k, c in enumerate(r):
                a = aligns[k] if k < len(aligns) and aligns[k] else ""
                style = f' style="text-align:{a}"' if a else ""
                inner = cell(c)
                if tag == "th":
                    tds.append(f'<th role="columnheader"{style}>{inner}</th>')
                    continue
                # on a narrow column docs.css lists each row as a block: the cell's column name comes from data-label
                label = f' data-label="{html.escape(labels[k])}"' if k < ncol else ""
                if ncol > 2 and k > 0 and inner:
                    inner = f'<span class="v">{inner}</span>'
                tds.append(f'<td role="cell"{label}{style}>{inner}</td>')
            return '<tr role="row">' + "".join(tds) + "</tr>"

        body = "\n".join(row_html(cells(r), "td") for r in rows)
        return (
            f'<div class="table" data-cols="{ncol}"><table role="table">\n'
            f'<thead role="rowgroup">{row_html(heads, "th")}</thead>\n'
            f'<tbody role="rowgroup">\n{body}\n</tbody>\n</table></div>'
        )


# ---------------------------------------------------------------------------------------------------------------
# site


@dataclass
class Page:
    group: str
    src: str
    slug: str
    label: str
    summary: str = ""
    title: str = ""
    body: str = ""
    description: str = ""
    toc: list = field(default_factory=list)
    ids: set = field(default_factory=set)


def page_url(base: str, slug: str) -> str:
    return base + (slug + "/" if slug else "")


def load_chrome(path: Path):
    """The site's shared header and footer (tools/chrome.py in the site repository)."""
    if not path.exists():
        sys.exit(f"shared chrome not found: {path} (pass --chrome /path/to/tools/chrome.py)")
    spec = importlib.util.spec_from_file_location("site_chrome", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page_list(source: Source) -> list[Page]:
    pages = []
    for p in PAGES:
        if not source.exists(p[1]):
            sys.exit(f"{p[1]} is listed in PAGES but not in {source.ref or 'the working tree'}")
        if len(p[4]) > 155:
            sys.exit(f"{p[1]}: meta description is {len(p[4])} characters; keep it under 155")
        pages.append(Page(*p))
    listed = {p.src for p in pages}
    for src in source.list("docs", ".md"):
        if src not in listed and src not in EXCLUDED:
            print(f"note: {src} is neither in PAGES nor in EXCLUDED; not published", file=sys.stderr)
    return pages


def build(out: Path, base: str, source: Source, chrome) -> list[Path]:
    pages = page_list(source)
    by_src = {p.src: p for p in pages}
    copies: dict[str, str] = {}  # repo path -> output-relative path (images)
    broken: list[str] = []

    for p in pages:
        src_dir = posixpath.dirname(p.src)

        def link(href: str, src_dir=src_dir, p=p) -> str | None:
            if href.startswith("/"):
                return href  # another part of the site (/runs/, ...)
            gh = GITHUB_DOC_RE.match(href)
            path, _, anchor = (gh.group(1) if gh else href).partition("#")
            if not path:
                return "#" + anchor if anchor else None
            target = posixpath.normpath(path if gh else posixpath.join(src_dir, path))
            frag = "#" + anchor if anchor else ""
            if target in by_src:
                return page_url(base, by_src[target].slug) + frag
            if (
                re.search(r"\.(png|jpe?g|gif|svg|webp)$", target, re.I)
                and target.startswith("docs/")
                and source.exists(target)
            ):
                rel = target[len("docs/") :]
                copies[target] = rel
                return base + rel
            if target.endswith(".md") and target.startswith("docs/"):
                broken.append(f"{p.src}: link to unpublished page {href}")
            return href if gh else None  # other GitHub links stay as they are

        md = source.read(p.src)
        md = re.sub(r"/Users/(?!<)[^/\s`]+/", "~/", md)  # tidy absolute home paths
        md = re.sub(
            r"^<!--.*?-->[ \t]*\n", "", md, flags=re.M
        )  # whole-line comments (generator markers) are not published

        def svg(href: str, src_dir=src_dir) -> str | None:
            target = posixpath.normpath(posixpath.join(src_dir, href))
            if not (target.startswith("docs/") and source.exists(target)):
                broken.append(f"{p.src}: missing figure {href}")
                return None

            def one(t: str) -> str:
                s = re.sub(r"<\?xml[^>]*>\s*|<!--.*?-->", "", source.read(t), flags=re.S).strip()
                uid = posixpath.splitext(posixpath.basename(t))[0]
                return re.sub(r'id="ah-([\w-]+)"', lambda m: f'id="{uid}-{m.group(1)}"', s).replace(
                    "url(#ah-", f"url(#{uid}-"
                )

            # X-narrow.svg, when there is one, is the same figure stacked for phones (docs.css shows one of the two)
            narrow = target[: -len(".svg")] + "-narrow.svg"
            if source.exists(narrow):
                return one(target).replace('class="fig"', 'class="fig fig-wide"', 1) + one(narrow).replace(
                    'class="fig"', 'class="fig fig-narrow"', 1
                )
            return one(target)

        def size(href: str, src_dir=src_dir) -> tuple[int, int] | None:
            target = posixpath.normpath(posixpath.join(src_dir, href))
            return image_size(source.read_bytes(target)) if source.exists(target) else None

        conv = Converter(link, {page_url(base, q.slug): q.label for q in pages}, svg, size)
        p.body = conv.blocks(md.splitlines())
        p.toc = [(lvl, hid, plain(text)) for lvl, hid, text in conv.headings if lvl in (2, 3)]
        p.ids = {hid for _, hid, _ in conv.headings}
        h1 = next((t for lvl, _, t in conv.headings if lvl == 1), p.label)
        p.title = plain(h1)
        paras = [
            b
            for b in re.split(r"\n\s*\n", md)
            if b.strip() and not b.lstrip().startswith(("#", "`", "|", "-", "!", ">"))
        ]
        desc = re.sub(r"\s+", " ", plain(paras[0])) if paras else p.title
        p.description = p.summary or (desc if len(desc) <= 180 else desc[:177].rsplit(" ", 1)[0] + "...")

    # every in-docs link must hit a page, and every #anchor a heading on it
    by_url = {page_url(base, q.slug): q for q in pages}
    for p in pages:
        for href in re.findall(r'href="([^"]+)"', p.body):
            href = html.unescape(href)
            if href.startswith("#"):
                if href[1:] not in p.ids:
                    broken.append(f"{p.src}: missing anchor {href}")
            elif href.startswith(base):
                path, _, anchor = href.partition("#")
                q = by_url.get(path)
                if q is None and not re.search(r"\.(png|jpe?g|gif|svg|webp)$", path):
                    broken.append(f"{p.src}: link to missing page {href}")
                elif q is not None and anchor and anchor not in q.ids:
                    broken.append(f"{p.src}: missing anchor {href}")
    if broken:
        sys.exit("broken links:\n  " + "\n  ".join(broken))

    # write
    if out.exists():
        if any(out.iterdir()) and not (out / MARKER).exists():
            sys.exit(f"refusing to clear {out}: not empty and not created by build_docs.py (no {MARKER})")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text(
        "generated by robouse/tools/docs/build_docs.py; the whole directory is replaced on rebuild\n"
    )
    (out / "docs.css").write_text(CSS, encoding="utf-8")
    (out / "docs.js").write_text(JS, encoding="utf-8")
    for src, rel in copies.items():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(source.read_bytes(src))
    written = []
    for k, p in enumerate(pages):
        prev_p = pages[k - 1] if k > 0 else None
        next_p = pages[k + 1] if k + 1 < len(pages) else None
        dst = out / p.slug / "index.html" if p.slug else out / "index.html"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(render(p, pages, base, prev_p, next_p, chrome), encoding="utf-8")
        written.append(dst)
    for old_slug, target in REDIRECTS.items():  # moved pages: a stub at the old URL that sends readers to the new one
        slug, _, anchor = target.partition("#")
        url = page_url(base, slug) + (f"#{anchor}" if anchor else "")
        dst = out / old_slug / "index.html"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            f'<!doctype html><meta charset="utf-8"><title>Moved</title><link rel="canonical" href="{url}">'
            f'<meta http-equiv="refresh" content="0; url={url}"><meta name="robots" content="noindex">'
            f'<p><a href="{url}">This page moved.</a></p>\n',
            encoding="utf-8",
        )
    return written


def toc_items(toc: list[tuple[int, str, str]]) -> str:
    """A page's sections as <li> items: each h2, with its h3s in a list under it. An h3 named after its h2 ("robouse
    tasks list" under "robouse tasks") is listed by the rest of its name ("list"); its link keeps the full name."""
    e = html.escape
    groups: list[tuple[str, str, list[str]]] = []
    for lvl, hid, text in toc:
        if lvl == 3 and groups:
            parent = groups[-1][1]
            short = text[len(parent) + 1 :] if text.startswith(parent + " ") else text
            name = f' aria-label="{e(text)}"' if short != text else ""
            groups[-1][2].append(f'<li><a href="#{e(hid)}"{name}>{e(short)}</a></li>')
        else:
            groups.append((hid, text, []))
    return "".join(
        f'<li><a href="#{e(hid)}">{e(text)}</a>' + (f'<ul>{"".join(subs)}</ul>' if subs else "") + "</li>"
        for hid, text, subs in groups
    )


def render(p: Page, pages: list[Page], base: str, prev_p: Page | None, next_p: Page | None, chrome) -> str:
    e = html.escape
    nav, group = [], None
    for q in pages:
        if q.group != group:
            if group is not None:
                nav.append("</ul>")
            group = q.group
            nav.append(f'<p class="grp">{e(group)}</p><ul>')
        cur = ' aria-current="page"' if q is p else ""
        # the current page's sections, under it: shown where there is no room for the on-this-page column (docs.css)
        secs = ""
        if q is p and len(p.toc) >= 2:
            secs = f'<ul class="secs">{toc_items(p.toc)}</ul>'
        nav.append(f'<li><a href="{page_url(base, q.slug)}"{cur}>{e(q.label)}</a>{secs}</li>')
    nav.append("</ul>")
    toc = ""
    if len(p.toc) >= 2:
        items = toc_items(p.toc)
        # plain containers: the navs inside are the landmarks (two unnamed asides were two identical complementary ones)
        toc = f'<div class="toc"><nav aria-label="On this page"><p class="grp">On this page</p><ul>{items}</ul></nav></div>'
    pager = []
    if prev_p:
        pager.append(f'<a class="prev" href="{page_url(base, prev_p.slug)}"><span>Previous</span>{e(prev_p.label)}</a>')
    if next_p:
        pager.append(f'<a class="next" href="{page_url(base, next_p.slug)}"><span>Next</span>{e(next_p.label)}</a>')
    title = "Docs · Robo Use" if not p.slug else f"{p.title} · Docs · Robo Use"
    canonical = "https://robouse.ai" + page_url(base, p.slug)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(p.description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Robo Use">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(p.description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{CARD}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.png">
<script src="/theme.js"></script>
{chrome.LINK}
<link rel="stylesheet" href="{base}docs.css">
{getattr(chrome, "BRIDGE", '<link rel="stylesheet" href="/surface.css">')}
<script src="{base}docs.js" defer></script>
<noscript><style>@media (max-width: 760px) {{ .side {{ display: block; }} .navbtn {{ display: none !important; }} }}</style></noscript>
</head>
<body>
{chrome.header("/docs/")}
<div class="shell{'' if toc else ' no-toc'}">
<button type="button" class="navbtn" aria-expanded="false" aria-controls="docs-nav">Menu<span class="cur">{e(p.label)}</span></button>
<div class="side" id="docs-nav"><nav aria-label="Docs">
{chr(10).join(nav)}
</nav></div>
<main class="doc">
<article class="prose">
{title_block(p.body)}
</article>
<nav class="pager">{"".join(pager)}</nav>
</main>
{toc}
</div>
{chrome.FOOTER}
</body>
</html>
"""


def title_block(body: str) -> str:
    """The page's h1 and its first paragraph as the site's shared title block (<header class="page-head">, .lede)."""
    m = re.match(r"\s*(<h1\b[^>]*>.*?</h1>)\s*(?:<p>(.*?)</p>)?", body, re.S)
    if not m:
        return body
    lede = f'<p class="lede">{m.group(2)}</p>' if m.group(2) is not None else ""
    return f'<header class="page-head">{m.group(1)}{lede}</header>\n' + body[m.end() :]


def check_output(out: Path) -> list[str]:
    problems = []
    for f in sorted(out.rglob("*")):
        if not f.is_file() or f.suffix not in {".html", ".css", ".js"}:
            continue
        text = f.read_text(encoding="utf-8")
        for w in BANNED_WORDS:
            if w in text.lower():
                problems.append(f"{f.relative_to(out)}: banned word (see BANNED_WORDS)")
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                problems.append(f"{f.relative_to(out)}: looks like a credential: {m.group(0)[:24]}...")
    return problems


CSS = r"""/* Robo Use docs. Generated by robouse/tools/docs/build_docs.py; edit the script, not this file.
   Tokens: /tokens.css. Headings, body text, links, code blocks and the copy button, tables, lists, quotes, captions and the
   title block: /prose.css. Focus ring and controls: /ui.css. Header and footer: /chrome.css. Page surface: /surface.css.
   This file is the docs layout: sidebar, page, on-this-page, pager, figures, the phone menu, and how tables, inline code
   and section links behave in the docs' columns. */
html { scroll-padding-top: var(--sp-20); }

/* layout: sidebar, page, on-this-page, on the site's 1120px grid. At full width the page column is 672 px, so an
   80-column terminal line (the CLIs' help, command output) fits in a code block without scrolling sideways. */
.shell { display: grid; grid-template-columns: 176px minmax(0, 1fr) 160px; gap: 0 var(--sp-32); max-width: var(--wide); margin: 0 auto;
  padding: var(--sp-72) max(var(--gutter), env(safe-area-inset-right)) 0 max(var(--gutter), env(safe-area-inset-left)); }
.shell.no-toc { grid-template-columns: 176px minmax(0, 1fr); }
/* the side columns stick; a small inset keeps the focus ring inside their scroll box */
.side, .toc { position: sticky; top: var(--sp-24); align-self: start; max-height: calc(100vh - var(--sp-48)); overflow-y: auto; overscroll-behavior: contain;
  margin: 0 calc(-1 * var(--sp-8)); padding: var(--sp-2) var(--sp-8); font: 400 var(--fs-small)/1.45 var(--sans); }
.grp { margin: var(--sp-28) 0 var(--sp-6); font: 600 var(--fs-small)/1.4 var(--sans); color: var(--ink); }
.side .grp:first-child, .toc .grp { margin-top: var(--sp-4); }
.side ul, .toc ul { list-style: none; margin: 0; padding: 0; }
.side li, .toc li { margin: 0; }
.side a, .toc a, .pager a { text-decoration: none; }
.side li a { display: block; margin: 0 calc(-1 * var(--sp-8)); padding: var(--sp-4) var(--sp-8); color: var(--muted); border-radius: var(--r-sm); transition: color var(--t-fast), background var(--t-fast); }
.side li a:hover { background: var(--hover); color: var(--ink); }
.side li a:active { background: var(--press); color: var(--ink2); }
.side li a:focus-visible { outline-offset: -2px; }
/* the current page: ink on a filled row, so it never reads as one more group label */
.side li a[aria-current="page"] { color: var(--ink); font-weight: 500; background: var(--press); }
/* the current page's sections under it, only where the on-this-page column is gone (below 1080 px, the phone menu) */
.side .secs { display: none; margin: var(--sp-2) 0 var(--sp-6); }
.side .secs a { padding-left: var(--sp-20); font-size: var(--fs-meta); }
.side .secs a.on { color: var(--ink); }
.toc li a { display: block; padding: var(--sp-4) 0 var(--sp-4) var(--sp-12); border-left: var(--hairline); color: var(--muted); line-height: 1.4;
  border-radius: 0; transition: color var(--t-fast), border-color var(--t-fast); }
.toc li a:hover { color: var(--ink); border-left-color: var(--line-strong); }
.toc li a.on { color: var(--ink); border-left-color: var(--ink); }
.toc li a:focus-visible { outline-offset: -2px; }
/* a section's subsections under it (the CLIs page's subcommands), indented on the same rule */
.toc li li a { padding-left: var(--sp-24); }
.side .secs li li a { padding-left: calc(var(--sp-20) + var(--sp-12)); }
.navbtn { display: none; }
.doc { min-width: 0; max-width: var(--measure); padding-bottom: var(--sp-24); }

/* section links: a # beside each h2 and h3 (beside, not inside, so the heading's name is only its text); following one
   also copies the section's address (docs.js). On touch screens, where nothing hovers, it stays faintly visible. */
.prose .hd { display: flex; align-items: baseline; gap: var(--sp-4); }
.prose .hd2 { margin: var(--sp-48) 0 var(--sp-12); }
.prose .hd3 { margin: var(--sp-32) 0 var(--sp-8); }
.prose .hd > :is(h2, h3, h4) { margin: 0; min-width: 0; }
.prose > .hd:first-child { margin-top: 0; }
.prose a.hash { flex: none; padding: 0 var(--sp-4); color: var(--faint); text-decoration: none; opacity: 0; font: 400 var(--fs-body)/1 var(--sans);
  border-radius: var(--r-xs); transition: opacity var(--t-fast), color var(--t-fast); }
.prose a.hash::before { content: "#"; }
.prose .hd:hover a.hash, .prose a.hash:focus-visible, .prose a.hash.done { opacity: 1; }
.prose a.hash:hover { color: var(--accent); }
.prose a.hash.done::after { content: "Copied"; margin-left: var(--sp-6); font: 400 var(--fs-caption)/1 var(--sans); color: var(--ok); }
@media (hover: none) { .prose a.hash { opacity: 1; } }
/* a heading that is one command (the CLIs page): the command in the mono face, not a chip. Weight 400, the mono face
   every page preloads: the 500 face is font-display: optional and not preloaded, so on a first visit it arrives too
   late and the heading would show at 400 anyway, then at 500 on the next visit */
.prose h2.cmd > code, .prose h3.cmd > code { font: 400 .875em/1.3 var(--mono); color: var(--ink); background: none; border: 0; padding: 0; }
.prose h3.cmd > code { font-size: 1em; }  /* 17 px, a step under the h2's 21 px and well over the help text's 13 px */
article img { display: block; max-width: 100%; height: auto; margin: var(--sp-8) 0; border-radius: var(--r-sm); border: var(--hairline); }

/* inline code breaks only between words (build_docs.py code_html): a one-word chip stays whole; a .brk chip breaks at its
   spaces with each word whole, a long word after a slash, and a part between slashes too long for a phone where it must */
.prose :not(pre) > code { white-space: nowrap; overflow-wrap: normal; }
.prose :not(pre) > code.brk { white-space: normal; overflow-wrap: anywhere; }
.prose code .w { white-space: nowrap; }

/* a code block or table that scrolls sideways takes keyboard focus (docs.js); its ring keeps the block's corners. Code
   blocks scroll only sideways: their height is their content's, so a rounding pixel never makes them scroll down */
.code > pre { overflow-y: hidden; }
.code > pre:focus-visible { border-radius: var(--r-md); }
.table:focus-visible { border-radius: var(--r-sm); }

/* tables. A cell's second line is a quieter note under its first (a suite's description under its id). When the column
   is too narrow for a table, each row becomes a block instead of scrolling sideways: its first cell as the title, then
   the other cells, each after its column name (data-label), side by side while they fit; a value too long to sit beside
   its name goes under it. Tables of two columns do so only on phones, without the names. */
.prose td .sub { display: block; margin-top: var(--sp-2); color: var(--muted); font-size: var(--fs-meta); line-height: 1.45; }
.table { container-type: inline-size; }
@container (max-width: 599px) {
  .table:not([data-cols="2"]) :is(table, tbody) { display: block; }
  .table:not([data-cols="2"]) thead { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .table:not([data-cols="2"]) tr { display: flex; flex-wrap: wrap; gap: var(--sp-4) var(--sp-24); padding: var(--sp-12) 0; border-bottom: var(--hairline); }
  .table:not([data-cols="2"]) tr > td { min-width: 0; max-width: 100%; padding: 0; border: 0; text-align: left; }
  .table:not([data-cols="2"]) tr > td:first-child { display: block; flex: 1 0 100%; margin-bottom: var(--sp-2); }
  .table:not([data-cols="2"]) tr > td + td { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: var(--sp-8); }
  .table:not([data-cols="2"]) tr > td + td::before { content: attr(data-label); color: var(--muted); font-size: var(--fs-meta); }
  .table:not([data-cols="2"]) tr > td > .v { min-width: 0; }
  .table:not([data-cols="2"]) tr > td:empty { display: none; }
}
@container (max-width: 439px) {
  .table[data-cols="2"] :is(table, tbody, tr, td) { display: block; }
  .table[data-cols="2"] thead { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .table[data-cols="2"] tr { padding: var(--sp-10) 0; border-bottom: var(--hairline); }
  .table[data-cols="2"] tr > td { padding: 0; border: 0; text-align: left; }
  .table[data-cols="2"] tr > td + td { margin-top: var(--sp-4); }
}

/* figures: inline SVG diagrams take the page's colours and type; stills are small webp images */
.figure { margin: var(--sp-24) 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.figure > svg { display: block; width: 100%; min-width: 500px; height: auto; overflow: visible; }  /* small screens scroll rather than shrink the type */
.figure > svg.fig-narrow { display: none; }
/* a figure with a stacked variant shows that instead on phones, and wherever its column is narrower than the wide
   drawing's 500 px (a tablet with the sidebar), at about the desktop's type size, so nothing scrolls sideways */
.figure.has-narrow { container-type: inline-size; }
@media (max-width: 640px) {
  .figure.has-narrow { overflow-x: visible; }
  .figure.has-narrow > svg.fig-wide { display: none; }
  .figure.has-narrow > svg.fig-narrow { display: block; width: 100%; min-width: 0; max-width: 316px; }
}
@container (max-width: 499px) {
  .figure.has-narrow > svg.fig-wide { display: none; }
  .figure.has-narrow > svg.fig-narrow { display: block; width: 100%; min-width: 0; max-width: 316px; }
}
.figure img { margin: 0; }
.fig { color: var(--ink); }
.fig text { font-family: var(--sans); font-size: var(--fs-meta); fill: var(--ink2); }
.fig .t { font-family: var(--serif); font-size: var(--fs-h3); fill: var(--ink); }
.fig .s { fill: var(--ink2); }
.fig .k { font-size: var(--fs-caption); fill: var(--muted); }
.fig .c { font-size: var(--fs-caption); fill: var(--muted); text-anchor: middle; }
.fig .end { text-anchor: end; }
.fig .m, .fig tspan.m { font-family: var(--mono); font-size: var(--fs-caption); fill: var(--ink); white-space: pre; }
.fig .m.o { fill: var(--muted); font-size: var(--fs-micro); }
.fig .m.b { font-weight: 500; }
.fig .box { fill: var(--paper); stroke: var(--line-strong); stroke-width: 1; }
.fig .box.trusted { stroke: var(--ink); }
.fig .box2 { fill: var(--panel); stroke: var(--line); stroke-width: 1; }
.fig .ln { stroke: var(--ink2); stroke-width: 1.3; fill: none; }
.fig .ln.thin { stroke: var(--muted); stroke-width: 1; }
.fig .ln.dash { stroke-dasharray: 4 4; stroke: var(--muted); }
.fig .fill { fill: var(--ink2); }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: var(--sp-16) var(--sp-12); margin: var(--sp-20) 0 var(--sp-24); }
.gallery figure { margin: 0; }
.gallery img { display: block; width: 100%; aspect-ratio: 1; object-fit: cover; margin: 0; border-radius: var(--r-sm); border: var(--hairline); }
.gallery figcaption { margin-top: var(--sp-6); font-size: var(--fs-meta); line-height: 1.35; }

/* pager: previous and next, each a generous target */
.pager { display: flex; justify-content: space-between; gap: var(--sp-16); margin-top: var(--sp-56); padding-top: var(--sp-12); border-top: var(--hairline); }
.pager a { display: flex; flex-direction: column; gap: var(--sp-6); min-width: 0; padding: var(--sp-8) 0; color: var(--ink); font: 400 var(--fs-body)/1.3 var(--sans);
  border-radius: var(--r-xs); transition: color var(--t-fast); }
.pager a:hover { color: var(--accent); }
.pager a:active { color: var(--ink2); }
.pager a span { font: 400 var(--fs-small)/1 var(--sans); color: var(--muted); }
.pager .next { margin-left: auto; text-align: right; }

@media (max-width: 1080px) {
  .shell, .shell.no-toc { grid-template-columns: 176px minmax(0, 1fr); }
  .toc { display: none; }
  .side .secs { display: block; }
}
@media (max-width: 760px) {
  html { scroll-padding-top: calc(var(--touch) + var(--sp-16)); }
  .shell, .shell.no-toc { display: block; padding-top: var(--sp-24); }
  /* the menu bar stays at the top of the screen; the menu opens under it as a sheet of its own (docs.js), with the
     current page's sections, so a long page keeps its contents at hand */
  .navbtn { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: var(--sp-10); width: 100%; min-height: var(--touch);
    margin: 0 0 var(--sp-24); padding: 0; border: 0; border-bottom: var(--hairline); border-radius: 0; background: var(--paper);
    font: 400 var(--fs-small)/1.2 var(--sans); color: var(--muted); text-align: left; cursor: pointer; transition: color var(--t-fast); }
  .navbtn:hover { color: var(--ink); }
  .navbtn:focus-visible { outline-offset: -2px; border-radius: var(--r-xs); }
  .navbtn .cur { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); font-weight: 500; }
  .navbtn::after { content: ""; flex: none; width: 7px; height: 7px; margin: -3px var(--sp-2) 0 auto; border: solid var(--muted); border-width: 0 1.4px 1.4px 0;
    transform: rotate(45deg); transition: transform var(--t) var(--ease); }
  .navbtn[aria-expanded="true"]::after { transform: translateY(3px) rotate(-135deg); }
  .side { display: none; }
  .nav-open .side { display: block; position: fixed; z-index: 19; top: var(--nav-top, 0px); right: 0; bottom: 0; left: 0; align-self: stretch; max-height: none; margin: 0;
    padding: var(--sp-4) max(var(--gutter), env(safe-area-inset-right)) var(--sp-32) max(var(--gutter), env(safe-area-inset-left));
    overflow-y: auto; overscroll-behavior: contain; background: var(--paper); }
  .side .grp { margin-top: var(--sp-16); }
  .side li a { display: flex; align-items: center; min-height: var(--touch); padding-top: 0; padding-bottom: 0; }
  .pager a { min-height: var(--touch); justify-content: center; }
}
/* touch screens: the copy button sits under its code block as a full-size target instead of over the first line, and
   the right-edge fade of a long block stops at the block's frame instead of hanging behind the button */
@media (hover: none) {
  .code { display: flex; flex-direction: column; }
  .code > .copy { position: static; align-self: flex-end; opacity: 1; min-height: var(--touch); margin: calc(-1 * var(--sp-8)) calc(-1 * var(--sp-10)) calc(-1 * var(--sp-16)); padding: 0 var(--sp-10);
    border: 0; background: none; font-size: var(--fs-caption); color: var(--muted); }
  .code.more::after { bottom: calc(var(--touch) - var(--sp-8) - var(--sp-16) + 1px); }
  .code > .copy::before { display: none; }
}
/* over a long first line the copy button's left edge fades the line out, instead of cutting through a letter */
.code > .copy::before { content: ""; position: absolute; top: -1px; bottom: -1px; right: calc(100% + 1px); width: var(--sp-24);
  background: linear-gradient(to right, transparent, var(--panel)); pointer-events: none; }
.copy.done { color: var(--ok); }
@media print { .side, .toc, .navbtn, .pager, .copy { display: none !important; } .shell { display: block; } }
"""

JS = r"""// Copy buttons for code blocks, prompt styling for console blocks, the section in view, scrolling blocks a keyboard can
// reach, section links that copy their address, and the phone menu. Generated by robouse/tools/docs/build_docs.py.
document.querySelectorAll(".code").forEach(function (box) {
  var code = box.querySelector("code");
  var text = code.textContent;
  var console = code.classList.contains("language-console");
  // In console blocks, "$ cmd" lines are commands and the rest is output. A command continues onto
  // the next line while its line ends in a backslash. Copy only the commands.
  var cmd = [];
  if (console) {
    var cont = false;
    code.innerHTML = text.split("\n").map(function (l) {
      var esc = l.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      var isCmd = l.indexOf("$ ") === 0, isCont = !isCmd && cont;
      if (isCmd) cmd.push(l.slice(2)); else if (isCont) cmd.push(l);
      cont = (isCmd || isCont) && /\\$/.test(l);
      return isCmd ? '<span class="p">$ </span>' + esc.slice(2) : isCont ? esc : '<span class="o">' + esc + "</span>";
    }).join("\n");
  }
  var copyText = console ? cmd.join("\n") : text;
  var b = document.createElement("button");
  b.type = "button"; b.className = "copy"; b.textContent = "Copy"; b.setAttribute("aria-live", "polite");
  b.setAttribute("data-hold", "Copied|Selected");  // /ui.js keeps the button as wide as its widest label, so it flips in place
  b.addEventListener("click", function () {
    (navigator.clipboard ? navigator.clipboard.writeText(copyText) : Promise.reject()).then(function () {
      b.textContent = "Copied"; b.classList.add("done");
      clearTimeout(b._t); b._t = setTimeout(function () { b.textContent = "Copy"; b.classList.remove("done"); }, 1400);
    }, function () {  // no clipboard: select the code so it can be copied by hand
      var r = document.createRange(); r.selectNodeContents(code); var s = getSelection(); s.removeAllRanges(); s.addRange(r);
      b.textContent = "Selected";
    });
  });
  box.appendChild(b);
});
// The section in view is marked in the on-this-page column and, where that column is gone, under the page in the sidebar.
(function () {
  var links = [].slice.call(document.querySelectorAll(".toc a, .side .secs a"));
  if (!links.length) return;
  var idOf = function (a) { return decodeURIComponent(a.getAttribute("href").slice(1)); };
  var ids = [];
  links.forEach(function (a) { if (ids.indexOf(idOf(a)) < 0) ids.push(idOf(a)); });
  var heads = ids.map(function (id) { return document.getElementById(id); });
  function update() {
    var cur = -1;  // above the first section nothing is current; at the very bottom the last section is
    heads.forEach(function (h, i) { if (h && h.getBoundingClientRect().top < 120) cur = i; });
    if (cur >= 0 && innerHeight + scrollY >= document.documentElement.scrollHeight - 2) cur = heads.length - 1;
    if (picked >= 0) cur = picked;  // the entry the reader clicked stays current until they scroll by themselves
    links.forEach(function (a) { a.classList.toggle("on", cur >= 0 && idOf(a) === ids[cur]); });
  }
  var picked = -1, release = function () { if (picked >= 0) { picked = -1; update(); } };
  // any in-page link to a section (a contents entry or a heading's own # link) makes that section current
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]'); if (!a) return;
    var i = ids.indexOf(idOf(a)); if (i >= 0) { picked = i; update(); }
  });
  ["wheel", "touchstart", "keydown"].forEach(function (t) { window.addEventListener(t, release, { passive: true }); });
  document.addEventListener("scroll", update, { passive: true });
  update();
})();
// A code block or table that scrolls sideways is a named region with a tab stop, so a keyboard can reach it and scroll it
// with the arrow keys; it loses both when it fits again (a wider window, a table listed as blocks).
(function () {
  var els = [].slice.call(document.querySelectorAll(".code > pre, .table"));
  if (!els.length) return;
  function section(el) {
    for (var s = el.previousElementSibling; s; s = s.previousElementSibling) {
      var h = /^H[1-6]$/.test(s.tagName) ? s : s.matches(".hd, .page-head") ? s.querySelector("h1, h2, h3, h4") : null;
      if (h) return h.textContent.trim();
    }
    return el.parentElement && !el.parentElement.classList.contains("prose") ? section(el.parentElement) : "";
  }
  var names = {};  // a block's name is its first command (with its continuation lines) or its section; repeats get a number
  els.forEach(function (el, i) {
    var n;
    if (el.tagName === "PRE") {
      var lines = el.textContent.split("\n"), cmd = [];
      for (var k = 0; k < lines.length; k++) { cmd.push(lines[k].replace(/^\$ /, "").replace(/\\$/, "").trim()); if (!/\\$/.test(lines[k])) break; }
      var first = cmd.join(" ");
      n = "Code: " + (first.length > 72 ? first.slice(0, 71) + "…" : first);
    } else {
      var h = section(el);
      n = "Table" + (h ? ": " + h : "");
    }
    names[n] = (names[n] || 0) + 1;
    el._name = names[n] > 1 ? n + " (" + names[n] + ")" : n;
  });
  function sync() {
    els.forEach(function (el) {
      var over = el.scrollWidth > el.clientWidth;  // any overflow, as assistive tools count it
      // /ui.js may have made it a region first, under a shared name ("Code"): the block's own name replaces that one,
      // so no two regions on a page have the same name
      if (over) { if (!el.hasAttribute("tabindex")) el.tabIndex = 0; el.setAttribute("role", "region"); el.setAttribute("aria-label", el._name); }
      else if (el.hasAttribute("tabindex")) { el.removeAttribute("tabindex"); el.removeAttribute("role"); el.removeAttribute("aria-label"); }
      else if (!el.hasAttribute("role")) el.removeAttribute("aria-label");  // ui.js took its stop away first
    });
  }
  sync();
  if (window.ResizeObserver) { var ro = new ResizeObserver(sync); els.forEach(function (el) { ro.observe(el); }); }
  else window.addEventListener("resize", sync);
  window.addEventListener("load", sync);  // web fonts change line widths
})();
// A section's # link also copies the section's address.
(function () {
  var live = document.createElement("span");
  live.className = "vh"; live.setAttribute("aria-live", "polite");
  document.body.appendChild(live);
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.hash");
    if (!a || !navigator.clipboard) return;
    navigator.clipboard.writeText(location.href.split("#")[0] + a.getAttribute("href")).then(function () {
      a.classList.add("done"); live.textContent = "Link copied";
      clearTimeout(a._t); a._t = setTimeout(function () { a.classList.remove("done"); live.textContent = ""; }, 1400);
    }, function () {});
  });
})();
// Phones: Menu opens the docs menu as a sheet under the bar; a link, Escape or Menu again closes it, and a page restored
// from the back-forward cache never comes back with it open.
(function () {
  var btn = document.querySelector(".navbtn"), shell = document.querySelector(".shell"), side = document.getElementById("docs-nav");
  if (!btn || !shell || !side) return;
  var isOpen = function () { return shell.classList.contains("nav-open"); };
  function place() { shell.style.setProperty("--nav-top", Math.max(0, Math.round(btn.getBoundingClientRect().bottom)) + "px"); }
  function set(open, focus) {
    shell.classList.toggle("nav-open", open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) place();
    if (!open && focus) btn.focus();
  }
  btn.addEventListener("click", function () { set(!isOpen()); });
  side.addEventListener("click", function (e) { if (isOpen() && e.target.closest("a")) set(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) set(false, true); });
  window.addEventListener("scroll", function () { if (isOpen()) place(); }, { passive: true });
  window.addEventListener("resize", function () { if (isOpen()) place(); });
  window.addEventListener("pageshow", function () { set(false); });
  var wide = window.matchMedia("(min-width: 761px)"), shut = function (m) { if (m.matches) set(false); };
  if (wide.addEventListener) wide.addEventListener("change", shut); else wide.addListener(shut);
})();
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out", required=True, type=Path, help="output directory (replaced if it was built by this script)"
    )
    ap.add_argument("--base", default="/docs/", help="URL path the output is served under (default /docs/)")
    ap.add_argument(
        "--chrome", type=Path, help="the site's tools/chrome.py (default: ../../tools/chrome.py from --out)"
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ref", default="HEAD", help="git revision to read docs/ from (default HEAD)")
    src.add_argument(
        "--worktree", action="store_true", help="read the working tree instead (uncommitted edits included)"
    )
    args = ap.parse_args()
    base = "/" + args.base.strip("/") + "/" if args.base.strip("/") else "/"
    out = args.out.expanduser().resolve()
    chrome = load_chrome((args.chrome or out.parent.parent / "tools" / "chrome.py").expanduser().resolve())
    written = build(out, base, Source(None if args.worktree else args.ref), chrome)
    problems = check_output(out)
    for f in sorted(out.rglob("*.html")):
        for m in re.finditer(r"\b[A-Z][A-Z_]*PLACEHOLDER[A-Z_]*\b|\bTODO\b|\bTBD\b", f.read_text(encoding="utf-8")):
            print(f"warning: {f.relative_to(out)}: unfinished text {m.group(0)!r}", file=sys.stderr)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {len(written)} pages to {out} ({size / 1024:.0f} KiB)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit("output check failed")


if __name__ == "__main__":
    main()
