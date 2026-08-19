#!/usr/bin/env python3
"""Enforce ADR 0033's claim vocabulary and banned-absolutes rules against
arena's reader-facing Markdown. AAASM-5798 / AAASM-5599.

Adapted from agent-assembly's `scripts/check_claim_vocabulary.py` (AAASM-5679),
via docs Hub's, python-sdk's, node-sdk's and go-sdk's (AAASM-5797/5798) ports.
Per AAASM-5795's federation-by-convention decision this is a ONE-TIME PORT,
not a shared dependency -- this file diverges independently from here.

File scope: `docs/**` (excluding `docs/samples/**`, generated match-report
samples -- this repo's own CLAUDE.md: "`reports/` other than `README.md` is
generated output, not hand-authored", and `docs/samples/` is the same kind of
generated report content), `README.md`, `CONTRIBUTING.md`, and
`agents/official/**` (first-party agents; this org's own authored prose).
Excludes `agents/community/**` (public submissions -- this org does not
author that prose, same reasoning as the `examples` repo's own adoption-
matrix note: "Restates only"), `reports/**` (generated match output, tracked
in git but not hand-authored), and `tests/fixtures/**` (adversarial/mock test
fixtures -- deliberately not real content, ADR 0034's own `test-fixture`
exempt class).

Run against tracked Markdown source:

    python3 scripts/check_claim_vocabulary.py
    python3 scripts/check_claim_vocabulary.py --diff-base origin/main

Exit 0 = clean or --report-only, 1 = a blocking claim published, 2 = the
checker could not prove itself (see --selftest).

Waivers: NONE of this file's rules are waivable. `claim-vocabulary.md` (in
agent-assembly) §7.1 states no waiver reaches a banned absolute
(`CLAIM-ABS-*`) or an undifferentiated verb (`CLAIM-VERB-01`) -- both are
unwaivable everywhere, not just in the repo that specification lives in.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Macros. Each carries its own non-capturing group -- textual substitution of
# a bare alternation silently changes what the collocation rules mean.
# --------------------------------------------------------------------------
MACROS: dict[str, str] = {
    "SEP": r"(?:[-‑_\s]+)",
    "DOC-NOUN": r"(?:reference|guide|list|example|walkthrough|inventory|history|re-audit|rewrite|set\b)",
    "GOV-NOUN": (
        r"(?:coverage|protection|mediation|interception|enforcement|visibility"
        r"|observability|monitoring|detection|inspection|audit(?:ing|s)?"
        r"|governance|security|telemetry)"
    ),
    "SUBJ": (
        r"(?:Agent\s+Assembly|Assembly|the\s+(?:gateway|proxy|runtime|SDK|sandbox"
        r"|platform|product|CLI|dashboard|policy\s+engine)|aa-[a-z-]+)"
    ),
}

NEG_PATTERN = re.compile(
    r"(?:\bno\b|\bnot\b|\bnever\b|\bneither\b|\bnor\b|\bwithout\b|\bnothing\b"
    r"|\bcannot\b|\bcan't\b|\bisn't\b|\baren't\b|\bdoesn't\b|\bdon't\b"
    r"|\brather\s+than\b|\binstead\s+of\b|\bnon-|\bunder-|\bincomplete\b)",
    re.IGNORECASE,
)
NEG_WINDOW_CHARS = 70
CLAUSE_BOUNDARIES = set(".;!?\n")

CFG_NOUN_PATTERN = re.compile(
    r"\s*(?:entry|entries|rule|rules|pattern|handler|route|case|branch|glob"
    r"|selector|wildcard|for\b)",
    re.IGNORECASE,
)

_FILLER = "\x00"
_NEWLINE_FILLER = "."


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str
    pattern: str
    guards: tuple[str, ...]


RULES: tuple[Rule, ...] = (
    Rule("CLAIM-ABS-01", "blocking", r"catch(?:es|ing)?<SEP>everything", ("NEG",)),
    Rule("CLAIM-ABS-02", "finding", r"catch[-‑_\s]?all", ("NEG", "CFG-NOUN")),
    Rule(
        "CLAIM-ABS-03",
        "blocking",
        r"(?:can\s?not|cannot|can't|could<SEP>not)<SEP>(?:be<SEP>)?bypass(?:ed)?",
        (),
    ),
    Rule("CLAIM-ABS-04", "blocking", r"un-?bypassable", ()),
    Rule("CLAIM-ABS-05", "blocking", r"nowhere<SEP>to<SEP>hide", ()),
    Rule("CLAIM-ABS-06", "finding", r"every<SEP>action", ("NEG",)),
    Rule("CLAIM-ABS-07", "blocking", r"every<SEP>tool<SEP>calls?", ("NEG",)),
    Rule("CLAIM-ABS-08", "blocking", r"no<SEP>code<SEP>changes?", ()),
    Rule("CLAIM-ABS-09", "blocking", r"immutable<SEP>audit", ()),
    Rule("CLAIM-ABS-10", "blocking", r"(?:full|whole)<SEP>fleet", ()),
    Rule(
        "CLAIM-ABS-11",
        "finding",
        r"\b(?:complete|comprehensive|universal)\s+(?!<DOC-NOUN>)[^.;:!?]{0,40}?\b<GOV-NOUN>\b",
        ("NEG",),
    ),
    Rule(
        "CLAIM-ABS-12",
        "finding",
        r"\b<GOV-NOUN>\b[^.;:!?]{0,40}?\b(?:is|are|was|were|remains?)\b"
        r"[^.;:!?]{0,15}?\b(?:complete|comprehensive|universal)\b",
        ("NEG",),
    ),
    Rule(
        "CLAIM-VERB-01",
        "finding",
        r"\b<SUBJ>\b[^.;:!?]{0,30}?\b(?:protects|enforces|catches|prevents"
        r"|guarantees|blocks|stops)\s+(?:the|a|an|all|every|any|its|their|each)?"
        r"\s*[a-z][a-z-]{2,}",
        ("NEG",),
    ),
)

QUOTE_RULE_ID = "CLAIM-QUOTE-01"


def _expand(pattern: str) -> str:
    for name, expansion in MACROS.items():
        pattern = pattern.replace(f"<{name}>", expansion)
    return pattern


COMPILED: tuple[tuple[Rule, re.Pattern[str]], ...] = tuple(
    (rule, re.compile(_expand(rule.pattern), re.IGNORECASE)) for rule in RULES
)

# --------------------------------------------------------------------------
# File scope.
# --------------------------------------------------------------------------
EXTENSIONS = {".md", ".markdown"}

INCLUDE_GLOBS = (
    "docs/**",
    "README.md",
    "agents/official/**",
    "CONTRIBUTING.md",
    "SECURITY.md",
)

EXCLUDE_GLOBS = (
    "docs/samples/**",
    "reports/**",
    "agents/community/**",
    "tests/fixtures/**",
    "verification-reports/**",
    "node_modules/**",
)


def _matches_any(path: str, globs: tuple[str, ...]) -> bool:
    for pattern in globs:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2])):
            return True
    return False


def in_scope(path: str) -> bool:
    if _matches_any(path, EXCLUDE_GLOBS):
        return False
    if Path(path).suffix not in EXTENSIONS:
        return False
    return _matches_any(path, INCLUDE_GLOBS)


def _is_repo_relative(root: Path, rel: str) -> bool:
    candidate = Path(rel)
    if candidate.is_absolute():
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
    return (root / rel).exists() or not candidate.is_absolute()


_SAFE_REF = re.compile(r"^[A-Za-z0-9._/~^@{}:-]+$")


def _changed_lines(root: Path, base: str, targets: list[str]) -> dict[str, set[int]]:
    """Line numbers added or modified since `base`, per file. Raised, not
    swallowed, on failure -- a silent "nothing changed" would pass everything.

    `base` is validated against a plain git-ref character set before it
    reaches subprocess (defence in depth; list-form argv with no shell=True
    is not exploitable regardless).
    """
    if not _SAFE_REF.match(base):
        raise ValueError(f"--diff-base {base!r} is not a plain git ref (letters, digits, '.', '_', '-', '/' only)")
    result = subprocess.run(  # NOSONAR (S4721): list-form argv, no shell=True; base validated above.
        ["git", "-c", "core.quotepath=false", "diff", "-U0", "--no-color", "--merge-base", base, "--", *targets],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff against {base!r} failed ({result.returncode}): {result.stderr.strip()}")

    changed: dict[str, set[int]] = {}
    current: str | None = None
    hunk = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")
    for line in result.stdout.split("\n"):
        if line.startswith("+++ b/"):
            current = line[6:]
            changed.setdefault(current, set())
        elif current and (m := hunk.match(line)):
            start = int(m.group(1))
            count = int(m.group(2) or 1)
            changed[current].update(range(start, start + count))
    return changed


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


# --------------------------------------------------------------------------
# Normalisation. Every step preserves length, so an offset in the normalised
# text is an offset in the original file.
# --------------------------------------------------------------------------
_BLOCK_START = re.compile(
    r"""^(?:
          \#{1,6}\           # ATX heading
        | [-*+]\             # bullet
        | \d+[.)]\           # ordered list
        | \|                 # table row
        | (?:`{3,}|~{3,})    # code fence
        | (?:\*\s*){3,}$|(?:-\s*){3,}$|(?:_\s*){3,}$   # thematic break
        | <[A-Za-z/!]        # HTML block
        | (?:\ {4}|\t)\S     # indented code
    )""",
    re.VERBOSE,
)
_BQ = re.compile(r"^((?:\s*>\s?)*)")


def _blockquote_depth(line: str) -> tuple[int, str]:
    match = _BQ.match(line)
    marker = match.group(1) if match else ""
    return marker.count(">"), line[len(marker):]


_META_TAG = re.compile(r"<meta\s[^>]*>", re.IGNORECASE | re.DOTALL)
_SETEXT_UNDERLINE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
_TITLE_DESC_LINE = re.compile(r"^\s*(?:title|description)\s*:", re.IGNORECASE)
_ATX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


def _opens_front_matter(lines: list[str]) -> bool:
    """True when a leading `---` is YAML front matter rather than a thematic
    break."""
    key = re.compile(r"^\s*[A-Za-z_][\w.-]*\s*:")
    for line in lines[1:]:
        if line.strip() in {"---", "..."}:
            return True
        if line.strip() and not key.match(line):
            return False
    return False


def _structural_ranges(text: str) -> list[tuple[int, int]]:
    """Offsets where a backticked or quoted banned absolute keeps its own
    severity: front matter, a heading, a `title:`/`description:` value, or a
    `<meta …>` tag."""
    ranges: list[tuple[int, int]] = []
    offset = 0
    lines = text.split("\n")
    offsets: list[int] = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line) + 1

    in_front_matter = False
    front_matter_lines: set[int] = set()
    for index, line in enumerate(lines):
        start, end = offset, offset + len(line)
        offset = end + 1

        if index == 0 and line.strip() == "---" and _opens_front_matter(lines):
            in_front_matter = True
            front_matter_lines.add(index)
            continue
        if in_front_matter:
            front_matter_lines.add(index)
            if line.strip() in {"---", "..."}:
                in_front_matter = False
            else:
                ranges.append((start, end))
            continue

        if _ATX_HEADING.match(line):
            ranges.append((start, end))
            continue
        if m := _TITLE_DESC_LINE.match(line):
            ranges.append((start + m.end(), end))
            continue

    for index in range(len(lines) - 1):
        if index in front_matter_lines or (index + 1) in front_matter_lines:
            continue
        if not _SETEXT_UNDERLINE.match(lines[index + 1]):
            continue
        body = lines[index]
        if not body.strip() or _BLOCK_START.match(body):
            continue
        start = offsets[index]
        ranges.append((start, start + len(body)))

    for m in _META_TAG.finditer(text):
        ranges.append((m.start(), m.end()))
    return ranges


def _in_ranges(ranges: list[tuple[int, int]], offset: int) -> bool:
    return any(lo <= offset < hi for lo, hi in ranges)


def _mask_code_regions(text: str, structural: list[tuple[int, int]] | None = None) -> str:
    """Returns a same-length string with exempt regions replaced by `_FILLER`."""
    chars = list(text)
    n = len(text)

    def blank(start: int, end: int) -> None:
        for i in range(start, min(end, n)):
            if chars[i] != "\n":
                chars[i] = _FILLER

    for m in re.finditer(r"<!--.*?-->", text, re.DOTALL):
        blank(m.start(), m.end())

    lines_span: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        lines_span.append((offset, offset + len(line), line))
        offset += len(line)

    fence: str | None = None
    for start, end, line in lines_span:
        stripped = line.lstrip()
        m = re.match(r"(`{3,}|~{3,})", stripped)
        if fence is None:
            if m:
                fence = m.group(1)
                blank(start, end)
        else:
            blank(start, end)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None

    for start, end, line in lines_span:
        if re.match(r"^(?:\ {4}|\t)\S", line):
            blank(start, end)

    masked = "".join(chars)

    structural = structural or []
    for m in re.finditer(r"(`+)[^`\n]*?\1", masked):
        if _in_ranges(structural, m.start()):
            continue
        blank(m.start(), m.end())
    masked = "".join(chars)

    for m in re.finditer(r"\]\([^)]*\)", masked):
        blank(m.start(), m.end())
    for m in re.finditer(r"<https?://[^>]*>|https?://\S+", masked):
        blank(m.start(), m.end())

    return "".join(chars)


def _join_soft_wraps(masked: str, original: str) -> str:
    orig_lines = original.split("\n")
    out = list(masked)
    offset = 0
    offsets: list[int] = []
    for line in orig_lines:
        offsets.append(offset)
        offset += len(line) + 1

    for i in range(len(orig_lines) - 1):
        first, second = orig_lines[i], orig_lines[i + 1]
        if not first.strip() or not second.strip():
            continue
        depth_a, body_a = _blockquote_depth(first)
        depth_b, body_b = _blockquote_depth(second)
        if depth_a != depth_b:
            continue
        if not body_a.strip() or not body_b.strip():
            continue
        if _BLOCK_START.match(body_b):
            continue
        newline_at = offsets[i] + len(first)
        if newline_at < len(out) and out[newline_at] == "\n":
            out[newline_at] = " "
    return "".join(out)


def _logical_line_bounds(text: str, index: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return start, (len(text) if end == -1 else end)


def _quoted_spans(segment: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for quote_open, quote_close in (('"', '"'), ("“", "”")):
        pending: int | None = None
        for i, ch in enumerate(segment):
            if quote_open == quote_close:
                if ch == quote_open:
                    if pending is None:
                        pending = i
                    else:
                        spans.append((pending, i + 1))
                        pending = None
            else:
                if ch == quote_open:
                    pending = i
                elif ch == quote_close and pending is not None:
                    spans.append((pending, i + 1))
                    pending = None
    return spans


def _neg_fires(text: str, match_start: int) -> bool:
    window_start = max(0, match_start - NEG_WINDOW_CHARS)
    i = match_start - 1
    while i >= window_start:
        if text[i] in CLAUSE_BOUNDARIES:
            window_start = i + 1
            break
        i -= 1
    return bool(NEG_PATTERN.search(text[window_start:match_start]))


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    col: int
    end_line: int
    rule_id: str
    severity: str
    message: str
    matched: str


def scan_text(path: str, original: str) -> list[Diagnostic]:
    structural = _structural_ranges(original)
    masked = _mask_code_regions(original, structural)
    normalised = _join_soft_wraps(masked, original)
    match_text = normalised.replace("\n", _NEWLINE_FILLER)

    line_starts = [0]
    for i, ch in enumerate(original):
        if ch == "\n":
            line_starts.append(i + 1)

    def position(offset: int) -> tuple[int, int]:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - line_starts[lo] + 1

    diagnostics: list[Diagnostic] = []
    for rule, compiled in COMPILED:
        for m in compiled.finditer(match_text):
            if "NEG" in rule.guards and _neg_fires(match_text, m.start()):
                continue
            if "CFG-NOUN" in rule.guards and CFG_NOUN_PATTERN.match(match_text, m.end()):
                continue

            line, col = position(m.start())
            end_line, _ = position(max(m.start(), m.end() - 1))
            matched = re.sub(r"\s+", " ", original[m.start():m.end()]).strip()

            start, end = _logical_line_bounds(normalised, m.start())
            rel = m.start() - start
            in_quote = any(
                lo <= rel < hi for lo, hi in _quoted_spans(match_text[start:end])
            ) and not _in_ranges(structural, m.start())
            if in_quote:
                diagnostics.append(Diagnostic(
                    path, line, col, end_line, QUOTE_RULE_ID, "info",
                    f"{rule.rule_id} phrase inside a quoted span (negative example)", matched,
                ))
            else:
                diagnostics.append(Diagnostic(
                    path, line, col, end_line, rule.rule_id, rule.severity,
                    f"banned claim wording ({rule.rule_id})", matched,
                ))
    return sorted(diagnostics, key=lambda d: (d.path, d.line, d.col, d.rule_id))


def _introduced(d: Diagnostic, touched: set[int]) -> bool:
    return any(line in touched for line in range(d.line, d.end_line + 1))


def scan_file(root: Path, rel: str) -> list[Diagnostic]:
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return scan_text(rel, text)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="explicit paths (default: repo scope)")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="never exit non-zero; used while the blocking baseline is non-empty",
    )
    parser.add_argument("--selftest", action="store_true", help="run built-in fixtures")
    parser.add_argument(
        "--diff-base",
        help="restrict BLOCKING diagnostics to lines added or modified since this ref",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    root = Path(args.root).resolve()
    if args.paths:
        targets = []
        for p in args.paths:
            candidate = Path(p)
            if candidate.is_absolute():
                try:
                    targets.append(str(candidate.relative_to(root)))
                except ValueError:
                    targets.append(str(candidate))
            else:
                targets.append(p)
        dropped = [t for t in targets if _is_repo_relative(root, t) and not in_scope(t)]
        if dropped:
            for t in dropped:
                print(f"skipped (outside scope): {t}")
            targets = [t for t in targets if t not in set(dropped)]
    else:
        targets = [p for p in tracked_files(root) if in_scope(p)]

    changed_lines: dict[str, set[int]] | None = None
    if args.diff_base:
        changed_lines = _changed_lines(root, args.diff_base, targets)

    diagnostics: list[Diagnostic] = []
    for rel in targets:
        for d in scan_file(root, rel):
            touched = changed_lines.get(d.path, set()) if changed_lines is not None else set()
            if changed_lines is not None and d.severity == "blocking" and not _introduced(d, touched):
                d = Diagnostic(
                    d.path, d.line, d.col, d.end_line, d.rule_id, "pre-existing",
                    d.message + " (pre-existing; not introduced by this change)", d.matched,
                )
            diagnostics.append(d)

    counts = {"blocking": 0, "finding": 0, "info": 0, "pre-existing": 0}
    for d in diagnostics:
        counts[d.severity] = counts.get(d.severity, 0) + 1
        print(f"{d.path}:{d.line}:{d.col} {d.rule_id} {d.severity} {d.message} — {d.matched!r}")

    print(
        f"\ncheck_claim_vocabulary: {len(targets)} file(s) scanned; "
        f"{counts['blocking']} blocking, {counts['finding']} finding, "
        f"{counts['info']} info, {counts['pre-existing']} pre-existing."
    )

    if args.report_only:
        return 0
    return 1 if counts["blocking"] else 0


# --------------------------------------------------------------------------
# Self-test. Each rule gets a positive case; every guard gets a case where it
# must suppress.
# --------------------------------------------------------------------------
SELFTEST_CASES: tuple[tuple[str, str | None], ...] = (
    ("eBPF catches everything else, including bypass attempts.", "CLAIM-ABS-01"),
    ("It does not catch everything.", None),
    ("The gateway cannot be bypassed by an agent.", "CLAIM-ABS-03"),
    ("An unbypassable control.", "CLAIM-ABS-04"),
    ("With all three layers there is nowhere to hide.", "CLAIM-ABS-05"),
    ("Checked before every tool call.", "CLAIM-ABS-07"),
    ("Deploy with no code changes.", "CLAIM-ABS-08"),
    ("Recorded in an immutable audit trail.", "CLAIM-ABS-09"),
    ("Rolled out across the whole fleet.", "CLAIM-ABS-10"),
    ("Governs the full fleet today.", "CLAIM-ABS-10"),
    ("complete coverage of agent traffic", "CLAIM-ABS-11"),
    ("There is no claim of complete detection.", None),
    ("catch-all rules are configured here", None),
    ("a catch-all promise", "CLAIM-ABS-02"),
    ("`immutable audit` is a banned phrase", None),
    ('The bug was "an immutable audit trail" on the front page.', QUOTE_RULE_ID),
    ("Checked before every action the agent takes.", "CLAIM-ABS-06"),
    ("Our coverage is complete.", "CLAIM-ABS-12"),
    ("Agent Assembly enforces a zero-trust posture.", "CLAIM-VERB-01"),
    ("```\nimmutable audit\n```", None),
    ("    immutable audit trail\n", None),
    ("<!-- immutable audit -->", None),
    ("See [the docs](https://example.com/immutable-audit-trail).", None),
    ("## Agent Assembly `catches everything` on your fleet", "CLAIM-ABS-01"),
    ('## The "immutable audit" trail', "CLAIM-ABS-09"),
    ('<meta name="description" content="an immutable audit trail">', "CLAIM-ABS-09"),
    ("---\ntitle: An `immutable audit` trail\n---\n", "CLAIM-ABS-09"),
    ("description: keeps an `immutable audit` trail\n", "CLAIM-ABS-09"),
    ("The phrase `catches everything` is banned in body copy.", None),
    ("It does not, per `RFC-1`, catch everything.", None),
    ("It does not, per RFC-1, catch everything.", None),
    ("This is not a claim of `verified` complete coverage.", None),
    ("a don`t\nkept in an immutable audit trail\na won`t\n", "CLAIM-ABS-09"),
    ("a complete guide to coverage", None),
    ("complete mediation of agent traffic", "CLAIM-ABS-11"),
    ("---\nsummary: kept in an `immutable audit` trail\nowner: platform\n---\n", "CLAIM-ABS-09"),
    ("Agent Assembly `catches everything`\n=====\n", "CLAIM-ABS-01"),
    ("---\n\nIt is not an `immutable audit` trail.\n", None),
    ("It keeps an `immutable audit` trail\n---\n", "CLAIM-ABS-09"),
)


def selftest() -> int:
    failures: list[str] = []
    for i, (text, expected) in enumerate(SELFTEST_CASES):
        diags = scan_text(f"<case {i}>", text)
        ids = sorted({d.rule_id for d in diags if d.severity != "pre-existing"})
        if expected is None:
            if ids:
                failures.append(f"case {i} {text!r}: expected none, got {ids}")
        elif expected not in ids:
            failures.append(f"case {i} {text!r}: expected {expected}, got {ids or 'NOTHING'}")

    if not in_scope("docs/architecture.md"):
        failures.append("in_scope() rejects a real docs/ page")
    if in_scope("docs/samples/winning-match/arena-report.md"):
        failures.append("in_scope() accepts a generated sample report")
    if in_scope("reports/latest.md"):
        failures.append("in_scope() accepts generated report output")
    if in_scope("agents/community/some-agent/README.md"):
        failures.append("in_scope() accepts a community-submitted agent")
    if not in_scope("agents/official/ci-debug-agent/README.md"):
        failures.append("in_scope() rejects a first-party official agent")
    if in_scope("tests/fixtures/github_maintainer_dungeon/README.md"):
        failures.append("in_scope() accepts a test fixture")
    if in_scope("docs/architecture.txt"):
        failures.append("in_scope() accepts a non-Markdown extension")

    if not _SAFE_REF.match("origin/main") or not _SAFE_REF.match("HEAD~1"):
        failures.append("_SAFE_REF rejects an ordinary git ref")
    if _SAFE_REF.match("; rm -rf /") or _SAFE_REF.match("$(whoami)"):
        failures.append("_SAFE_REF accepts a shell-metacharacter string as a git ref")

    total = len(SELFTEST_CASES) + 9
    print(f"check_claim_vocabulary selftest: {total - len(failures)}/{total} checks passed")
    for f in failures:
        print("  FAIL:", f)
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
