#!/usr/bin/env python3
"""Validate real positive/negative trigger coverage for active Codex skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MIN_CASES = 4


def nonempty_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def main() -> int:
    skill_names = {
        path.parent.name for path in (ROOT / ".agents/skills").glob("*/SKILL.md")
    }
    errors: list[str] = []
    matrix_path = ROOT / "src/tests/harness/trigger-matrix.yaml"

    if not matrix_path.is_file():
        errors.append("missing trigger matrix: src/tests/harness/trigger-matrix.yaml")
        data: dict[str, Any] = {}
    else:
        try:
            loaded = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                errors.append("trigger matrix root must be an object")
        except Exception as exc:
            errors.append(f"invalid trigger matrix YAML: {exc}")
            data = {}

    entries = data.get("skills", [])
    if data.get("schemaVersion") != "1.0":
        errors.append("trigger matrix schemaVersion must be 1.0")
    if not isinstance(entries, list):
        errors.append("trigger matrix skills must be a list")
        entries = []

    covered: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"trigger matrix entry {index} must be an object")
            continue
        skill = entry.get("skill")
        if not isinstance(skill, str) or not skill.strip():
            errors.append(f"trigger matrix entry {index} has no skill name")
            continue
        if skill in covered:
            errors.append(f"duplicate trigger matrix entry: {skill}")
        covered.add(skill)
        if skill not in skill_names:
            errors.append(f"trigger matrix references missing skill: {skill}")

        positives = entry.get("shouldTrigger")
        negatives = entry.get("shouldNotTrigger")
        if not nonempty_strings(positives):
            errors.append(f"{skill}: shouldTrigger must contain non-empty strings")
        elif len(positives) < MIN_CASES:
            errors.append(f"{skill}: needs at least {MIN_CASES} shouldTrigger cases")
        elif len(set(positives)) != len(positives):
            errors.append(f"{skill}: duplicate shouldTrigger cases")
        if not nonempty_strings(negatives):
            errors.append(f"{skill}: shouldNotTrigger must contain non-empty strings")
        elif len(negatives) < MIN_CASES:
            errors.append(f"{skill}: needs at least {MIN_CASES} shouldNotTrigger cases")
        elif len(set(negatives)) != len(negatives):
            errors.append(f"{skill}: duplicate shouldNotTrigger cases")
        if nonempty_strings(positives) and nonempty_strings(negatives):
            overlap = set(positives) & set(negatives)
            if overlap:
                errors.append(
                    f"{skill}: positive/negative cases overlap: {sorted(overlap)}"
                )

    for skill in sorted(skill_names - covered):
        errors.append(f"skill missing from trigger matrix: {skill}")

    # Metadata remains useful for external eval runners, but is not trigger coverage.
    eval_root = ROOT / "src/tests/harness/evals"
    for path in sorted(eval_root.glob("*/eval_metadata.json")):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid eval metadata {path.relative_to(ROOT)}: {exc}")
            continue
        if not isinstance(metadata, dict):
            errors.append(f"eval metadata must be an object: {path.relative_to(ROOT)}")
            continue
        prompt = metadata.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"eval metadata prompt is empty: {path.relative_to(ROOT)}")

    if errors:
        print("HARNESS TRIGGER VALIDATION FAILED")
        for error in errors:
            print("-", error)
        return 1

    print(
        f"HARNESS TRIGGER MATRIX OK: {len(skill_names)} skills, "
        f">={MIN_CASES} positive and negative cases each"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
