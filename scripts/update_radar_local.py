#!/usr/bin/env python3
"""Safely finalize Kathy Outdoor Radar on Kathy's Mac only."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RADAR_DIR = ROOT / "01_營運後台" / "每日戶外情報"
GUARD = RADAR_DIR / "radar_ig_guard.py"
FINAL_HTML = RADAR_DIR / "Kathy_Outdoor_Radar.html"
FINAL_MD = RADAR_DIR / "Kathy_Outdoor_Radar_Latest.md"
DEFAULT_CANDIDATE_HTML = Path("/tmp/Kathy_Outdoor_Radar_candidate.html")
DEFAULT_CANDIDATE_MD = Path("/tmp/Kathy_Outdoor_Radar_candidate.md")


def run_guard(*args: str, guard_path: Path = GUARD) -> str:
    result = subprocess.run(
        [sys.executable, str(guard_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def stage_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, tempfile.NamedTemporaryFile(
        "wb", dir=destination.parent, delete=False, suffix=".tmp"
    ) as target_handle:
        shutil.copyfileobj(source_handle, target_handle)
        target_handle.flush()
        os.fsync(target_handle.fileno())
        return Path(target_handle.name)


def finalize(
    candidate_html: Path,
    candidate_md: Path,
    *,
    final_html: Path = FINAL_HTML,
    final_md: Path = FINAL_MD,
    guard_path: Path = GUARD,
) -> tuple[str, str]:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("Kathy Outdoor Radar is local-only; GitHub Actions is blocked")

    for candidate in (candidate_html, candidate_md):
        if not candidate.is_file():
            raise FileNotFoundError(f"candidate file not found: {candidate}")
    if not final_html.is_file():
        raise FileNotFoundError(f"previous HTML not found: {final_html}")

    repair_output = run_guard(
        "repair",
        str(candidate_html),
        "--previous",
        str(final_html),
        guard_path=guard_path,
    )
    validate_output = run_guard(
        "validate", str(candidate_html), guard_path=guard_path
    )

    staged_html = stage_copy(candidate_html, final_html)
    staged_md = stage_copy(candidate_md, final_md)
    try:
        staged_html.replace(final_html)
        staged_md.replace(final_md)
    finally:
        staged_html.unlink(missing_ok=True)
        staged_md.unlink(missing_ok=True)

    candidate_html.unlink()
    candidate_md.unlink()
    return repair_output, validate_output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate local Radar candidates before replacing the fixed files."
    )
    parser.add_argument("--candidate-html", type=Path, default=DEFAULT_CANDIDATE_HTML)
    parser.add_argument("--candidate-md", type=Path, default=DEFAULT_CANDIDATE_MD)
    args = parser.parse_args()

    try:
        repair_output, validate_output = finalize(
            args.candidate_html, args.candidate_md
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(repair_output)
    print(validate_output)
    print(f"UPDATED {FINAL_HTML}")
    print(f"UPDATED {FINAL_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
