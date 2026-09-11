#!/usr/bin/env python3
"""Check that the UI thresholds in the design and audit references agree.

``soia-dev-design-ui`` and ``soia-dev-audit-ui`` install independently, so each
skill keeps a complete copy of the shared numeric thresholds. The two copies
are kept comparable by machine-readable markers on the threshold rows:

    <!-- ui-threshold: <key> = <value> -->

``skills/soia-dev-design-ui/references/craft-floor.md`` is the design-side file
and ``skills/soia-dev-audit-ui/references/technical-checks.md`` is the audit-side
file. This script reads every marker from both files and fails when a shared key
is present on only one side or carries a different value.

Exit codes:
    0  every shared threshold is present on both sides and agrees
    1  drift found (missing counterpart, value mismatch, duplicate key)
    2  the check could not run (file missing or no markers to compare)

Values are compared after normalisation, so ``>= 4.5:1`` and ``≥ 4.5:1`` are
the same threshold. Write marker values in ASCII (``>=``, ``-``, ``x``) as the
canonical form and keep the typographic form in the visible prose.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER_RE = re.compile(r"<!--\s*ui-threshold:\s*([A-Za-z0-9._-]+)\s*=\s*(.+?)\s*-->")
SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = SKILL_DIR.parent
DEFAULT_DESIGN_FILE = SKILL_DIR / "references" / "craft-floor.md"
DEFAULT_AUDIT_FILE = SKILLS_DIR / "soia-dev-audit-ui" / "references" / "technical-checks.md"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CANNOT_RUN = 2

SYMBOL_REPLACEMENTS = (
    ("≥", ">="),
    ("≤", "<="),
    ("–", "-"),
    ("—", "-"),
    ("−", "-"),
    ("×", "x"),
    ("✕", "x"),
)


def normalize_value(value: str) -> str:
    """Reduce a threshold value to a comparable canonical string."""
    text = value.strip()
    for source, target in SYMBOL_REPLACEMENTS:
        text = text.replace(source, target)
    return re.sub(r"\s+", "", text)


def parse_markers(text: str) -> tuple[dict[str, str], list[str]]:
    """Return (key -> value, duplicate keys) for every marker in one file."""
    values: dict[str, str] = {}
    duplicates: list[str] = []
    for match in MARKER_RE.finditer(text):
        key = match.group(1)
        if key in values:
            duplicates.append(key)
        values[key] = match.group(2).strip()
    return values, duplicates


def evaluate(design_text: str, audit_text: str) -> tuple[int, list[str], list[str]]:
    """Compare two reference texts; return (exit code, problems, ok lines)."""
    design, design_duplicates = parse_markers(design_text)
    audit, audit_duplicates = parse_markers(audit_text)

    problems: list[str] = []
    ok_lines: list[str] = []

    if design_duplicates:
        problems.append(f"design file repeats marker key(s): {', '.join(sorted(set(design_duplicates)))}")
    if audit_duplicates:
        problems.append(f"audit file repeats marker key(s): {', '.join(sorted(set(audit_duplicates)))}")
    if not design:
        problems.append("design file carries no ui-threshold marker")
    if not audit:
        problems.append("audit file carries no ui-threshold marker")
    if problems:
        return EXIT_CANNOT_RUN, problems, ok_lines

    for key in sorted(set(design) | set(audit)):
        if key not in design:
            problems.append(f"{key}: present in audit file only (value {audit[key]!r})")
        elif key not in audit:
            problems.append(f"{key}: present in design file only (value {design[key]!r})")
        elif normalize_value(design[key]) != normalize_value(audit[key]):
            problems.append(
                f"{key}: value drift — design {design[key]!r} vs audit {audit[key]!r}"
            )
        else:
            ok_lines.append(f"{key} = {normalize_value(design[key])}")

    return (EXIT_DRIFT if problems else EXIT_OK), problems, ok_lines


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


SELFTEST_CASES = (
    (
        "agreeing pair passes",
        "| a | >= 4.5:1 <!-- ui-threshold: contrast.body = >= 4.5:1 --> |",
        "| a | ≥ 4.5:1 <!-- ui-threshold: contrast.body = >= 4.5:1 --> |",
        EXIT_OK,
    ),
    (
        "typographic and ASCII spellings are the same value",
        "<!-- ui-threshold: line-width.body = 65-75ch -->",
        "<!-- ui-threshold: line-width.body = 65–75ch -->",
        EXIT_OK,
    ),
    (
        "value drift fails",
        "<!-- ui-threshold: perf.lcp = < 2.5s -->",
        "<!-- ui-threshold: perf.lcp = < 3.0s -->",
        EXIT_DRIFT,
    ),
    (
        "one-sided key fails",
        "<!-- ui-threshold: perf.lcp = < 2.5s -->",
        "<!-- ui-threshold: perf.inp = < 200ms -->",
        EXIT_DRIFT,
    ),
    (
        "missing markers cannot be compared",
        "plain prose without markers",
        "plain prose without markers",
        EXIT_CANNOT_RUN,
    ),
    (
        "duplicate key cannot be compared",
        "<!-- ui-threshold: perf.cls = < 0.1 -->\n<!-- ui-threshold: perf.cls = < 0.2 -->",
        "<!-- ui-threshold: perf.cls = < 0.1 -->",
        EXIT_CANNOT_RUN,
    ),
)


def run_selftest() -> int:
    failures = 0
    for name, design_text, audit_text, expected in SELFTEST_CASES:
        code, problems, _ = evaluate(design_text, audit_text)
        if code != expected:
            failures += 1
            print(f"FAIL: {name}: expected exit {expected}, got {code}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"ok: {name} (exit {code})")
    if failures:
        print(f"selftest failed: {failures}/{len(SELFTEST_CASES)} case(s)")
        return EXIT_DRIFT
    print(f"selftest passed: {len(SELFTEST_CASES)} case(s)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that design and audit UI threshold markers agree."
    )
    parser.add_argument("--design-file", default=str(DEFAULT_DESIGN_FILE), help="design-side reference file")
    parser.add_argument("--audit-file", default=str(DEFAULT_AUDIT_FILE), help="audit-side reference file")
    parser.add_argument("--selftest", action="store_true", help="run fixture checks and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()

    design_path = Path(args.design_file)
    audit_path = Path(args.audit_file)
    for path in (design_path, audit_path):
        if not path.is_file():
            print(f"cannot run: file not found: {path}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    code, problems, ok_lines = evaluate(read_text(design_path), read_text(audit_path))
    if code == EXIT_CANNOT_RUN:
        for problem in problems:
            print(f"cannot run: {problem}", file=sys.stderr)
        return code
    if code == EXIT_DRIFT:
        for problem in problems:
            print(f"DRIFT: {problem}")
        print(f"checked {len(ok_lines) + len(problems)} shared key(s); fix both files together")
        return code

    print(f"OK: {len(ok_lines)} shared UI threshold(s) agree")
    for line in ok_lines:
        print(f"  {line}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
