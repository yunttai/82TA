#!/usr/bin/env python3
"""Validate active filesystem-backed Codex agents and skills."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
LEGACY_REGISTRY = ROOT / "src/contracts/harness/harness-registry.v1.yaml"
ALLOWED_EFFORT = {"low", "medium", "high", "xhigh", "max", "ultra"}


def frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise ValueError("missing YAML frontmatter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be an object")
    return data


def main() -> int:
    errors: list[str] = []

    try:
        config = tomllib.loads(
            (ROOT / ".codex/config.toml").read_text(encoding="utf-8")
        )
        agents_config = config.get("agents", {})
        if not isinstance(agents_config, dict):
            errors.append(".codex/config.toml agents must be a table")
        else:
            concurrency = agents_config.get("max_concurrent_threads_per_session", 1)
            if not isinstance(concurrency, int) or concurrency < 1:
                errors.append("agent concurrency must be a positive integer")
            effort = agents_config.get("default_subagent_reasoning_effort", "medium")
            if effort not in ALLOWED_EFFORT:
                errors.append(f"unsupported default reasoning effort: {effort}")
    except Exception as exc:
        errors.append(f"invalid .codex/config.toml: {exc}")

    agent_names: set[str] = set()
    for path in sorted((ROOT / ".codex/agents").glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for key in ("name", "description", "developer_instructions"):
                if not isinstance(data.get(key), str) or not data[key].strip():
                    errors.append(f"{path.relative_to(ROOT)}: {key} is required")
            name = data.get("name")
            if isinstance(name, str):
                if name in agent_names:
                    errors.append(f"duplicate custom agent name: {name}")
                agent_names.add(name)
                if name != path.stem:
                    errors.append(f"custom agent name/path mismatch: {path.relative_to(ROOT)}")
            effort = data.get("model_reasoning_effort")
            if effort is not None and effort not in ALLOWED_EFFORT:
                errors.append(f"{path.relative_to(ROOT)}: unsupported effort {effort}")
        except Exception as exc:
            errors.append(f"invalid custom agent {path.relative_to(ROOT)}: {exc}")

    skill_names: set[str] = set()
    for path in sorted((ROOT / ".agents/skills").glob("*/SKILL.md")):
        try:
            data = frontmatter(path)
            for key in ("name", "description"):
                if not isinstance(data.get(key), str) or not data[key].strip():
                    errors.append(f"{path.relative_to(ROOT)}: {key} is required")
            name = data.get("name")
            if isinstance(name, str):
                if name in skill_names:
                    errors.append(f"duplicate skill name: {name}")
                skill_names.add(name)
                if name != path.parent.name:
                    errors.append(f"skill name/path mismatch: {path.relative_to(ROOT)}")
        except Exception as exc:
            errors.append(f"invalid skill {path.relative_to(ROOT)}: {exc}")

    if not agent_names:
        errors.append("no project custom agents found")
    if not skill_names:
        errors.append("no project skills found")

    # The locked v1 registry is retained as a historical compatibility record.
    # Active discovery comes from .codex/agents and .agents/skills, so the registry
    # does not force exact role sets, path ownership, orchestrators, or workspace files.
    if LEGACY_REGISTRY.is_file():
        try:
            yaml.safe_load(LEGACY_REGISTRY.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid legacy registry YAML: {exc}")

    if errors:
        print("HARNESS REGISTRY VALIDATION FAILED")
        for error in errors:
            print("-", error)
        return 1

    legacy = "legacy registry retained as non-authoritative"
    print(
        f"ACTIVE CODEX HARNESS OK: {len(agent_names)} agents, "
        f"{len(skill_names)} skills; {legacy}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
