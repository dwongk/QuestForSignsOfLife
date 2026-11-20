#!/usr/bin/env python3
"""Compare a generated static site with the previously published site source."""
import argparse
import difflib
import hashlib
import os
from pathlib import Path
from typing import Optional


SITE_FILES = ("index.html", "styles.css", "images")
MAX_DIFF_LINES = 120


def files_by_path(root: Path) -> dict[str, Path]:
    files = {}
    for name in SITE_FILES:
        path = root / name
        if path.is_file():
            files[name] = path
        elif path.is_dir():
            files.update(
                (child.relative_to(root).as_posix(), child)
                for child in path.rglob("*")
                if child.is_file()
            )
    return files


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_summary(markdown: str):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(markdown)
            summary.write("\n")


def set_output(name: str, value: str):
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")


def compare(baseline: Optional[Path], generated: Path) -> tuple[list[str], list[str], list[str]]:
    generated_files = files_by_path(generated)
    baseline_files = files_by_path(baseline) if baseline else {}
    added = sorted(generated_files.keys() - baseline_files.keys())
    removed = sorted(baseline_files.keys() - generated_files.keys())
    changed = sorted(
        name
        for name in generated_files.keys() & baseline_files.keys()
        if sha256(generated_files[name]) != sha256(baseline_files[name])
    )
    return added, removed, changed


def html_diff(baseline: Optional[Path], generated: Path) -> list[str]:
    old_path = baseline / "index.html" if baseline else None
    new_path = generated / "index.html"
    old_lines = old_path.read_text(encoding="utf-8").splitlines() if old_path and old_path.is_file() else []
    new_lines = new_path.read_text(encoding="utf-8").splitlines() if new_path.is_file() else []
    return list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="published/index.html",
            tofile="generated/index.html",
            lineterm="",
        )
    )


def write_summary(baseline: Optional[Path], generated: Path):
    added, removed, changed = compare(baseline, generated)
    differences = added + removed + changed
    set_output("changed", "true" if differences else "false")

    if not differences:
        append_summary(
            "### Published-site comparison\n\n"
            "The generated website exactly matches the published-site source. "
            "The Pages deployment will be skipped.\n"
        )
        return

    lines = [
        "### Published-site comparison",
        "",
        f"**{len(differences)} site file(s) differ.** The site changes are expected and do not fail validation.",
        "",
        "| Change | File |",
        "| --- | --- |",
    ]
    lines.extend(f"| Added | `{name}` |" for name in added)
    lines.extend(f"| Removed | `{name}` |" for name in removed)
    lines.extend(f"| Updated | `{name}` |" for name in changed)

    if baseline:
        diff_lines = html_diff(baseline, generated)
        if diff_lines:
            displayed = diff_lines[:MAX_DIFF_LINES]
            lines.extend(["", "<details>", "<summary>Generated HTML diff</summary>", "", "```diff"])
            lines.extend(displayed)
            if len(diff_lines) > MAX_DIFF_LINES:
                lines.extend(["", f"... {len(diff_lines) - MAX_DIFF_LINES} additional diff lines omitted"])
            lines.extend(["```", "", "</details>"])
    else:
        lines.extend(["", "No prior site baseline was available; all generated files are treated as new."])

    lines.extend(
        [
            "",
            "Review the generated website using the `generated-gallery-preview` artifact. "
            "On pushes to `main`, deployment proceeds after the GitHub Pages environment's review gate, if configured.",
            "",
        ]
    )
    append_summary("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--generated", type=Path, required=True)
    args = parser.parse_args()

    if not args.generated.is_dir():
        parser.error(f"generated site directory does not exist: {args.generated}")
    if args.baseline and not args.baseline.is_dir():
        parser.error(f"baseline site directory does not exist: {args.baseline}")

    write_summary(args.baseline, args.generated)


if __name__ == "__main__":
    main()
