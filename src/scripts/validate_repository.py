#!/usr/bin/env python3
"""Validate repository layout, active Codex controls, and optional product contracts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

from _contract_utils import canonical_files, project_root

ALLOWED_ROOT_DIRS = {
    ".agents",
    ".codegraph",
    ".codex",
    ".git",
    ".github",
    "_workspace",
    "src",
}
ALLOWED_ROOT_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "README.md",
}
ALLOWED_ROOT_DOC_PREFIXES = (
    "CODE_OF_CONDUCT",
    "CONTRIBUTING",
    "LICENSE",
    "NOTICE",
    "SECURITY",
)
CODE_EXT = {
    ".bash", ".c", ".cjs", ".cpp", ".go", ".h", ".hpp", ".ipynb",
    ".java", ".js", ".jsx", ".kt", ".mjs", ".ps1", ".py", ".pyi",
    ".rs", ".sh", ".sql", ".tf", ".tfvars", ".ts", ".tsx", ".zsh",
}
ALLOWED_EFFORT = {"low", "medium", "high", "xhigh", "max", "ultra"}


def parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise ValueError("missing YAML frontmatter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be an object")
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key} required")
    return data


def parse_agent(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "description", "developer_instructions"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key} required")
    return data


def root_item_allowed(path: Path) -> bool:
    if path.is_dir():
        return path.name in ALLOWED_ROOT_DIRS
    if path.name in ALLOWED_ROOT_FILES:
        return True
    return path.name.startswith(ALLOWED_ROOT_DOC_PREFIXES)


def layout_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not root_item_allowed(path):
            errors.append(f"root item violates product-under-src policy: {path.name}")

    if (root / ".claude").exists() or (root / "CLAUDE.md").exists():
        errors.append("active legacy Claude control files remain")

    github = root / ".github"
    if github.exists():
        for path in github.rglob("*"):
            if path.is_symlink():
                errors.append(
                    f"GitHub control path must not be a symlink: {path.relative_to(root)}"
                )

    for base in (root / ".agents", root / ".codex"):
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix.lower() in CODE_EXT:
                    errors.append(
                        f"executable product-like file outside src: {path.relative_to(root)}"
                    )

    for workstream in (
        root / "src/docs/harnesses/service-product",
        root / "src/docs/harnesses/routing-intelligence",
    ):
        if not workstream.exists():
            continue
        for path in workstream.rglob("*"):
            if path.suffix.lower() in {".dbml", ".json", ".yaml", ".yml"}:
                errors.append(
                    f"duplicated machine contract in workstream docs: {path.relative_to(root)}"
                )

    agent_instruction_files = [
        root / "AGENTS.md",
        *sorted((root / "src").rglob("AGENTS.md")),
    ]
    for path in agent_instruction_files:
        if path.is_file() and path.stat().st_size > 65536:
            errors.append(f"AGENTS.md too large: {path.relative_to(root)}")
    return errors


def harness_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in ("AGENTS.md", ".codex/config.toml"):
        if not (root / relative).is_file():
            errors.append(f"required active harness file missing: {relative}")

    try:
        config = tomllib.loads(
            (root / ".codex/config.toml").read_text(encoding="utf-8")
        )
        agents_config = config.get("agents", {})
        if not isinstance(agents_config, dict):
            errors.append(".codex/config.toml agents must be a table")
        else:
            concurrency = agents_config.get("max_concurrent_threads_per_session", 1)
            if not isinstance(concurrency, int) or concurrency < 1:
                errors.append("Codex agent concurrency must be a positive integer")
            effort = agents_config.get(
                "default_subagent_reasoning_effort", "medium"
            )
            if effort not in ALLOWED_EFFORT:
                errors.append(f"unsupported default reasoning effort: {effort}")
    except Exception as exc:
        errors.append(f"invalid .codex/config.toml: {exc}")

    agent_names: set[str] = set()
    linked_skills: dict[str, set[str]] = {}
    for path in sorted((root / ".codex/agents").glob("*.toml")):
        try:
            data = parse_agent(path)
            name = data["name"]
            if name in agent_names:
                errors.append(f"duplicate custom agent: {name}")
            agent_names.add(name)
            if name != path.stem:
                errors.append(
                    f"custom agent name/path mismatch: {path.relative_to(root)}"
                )
            effort = data.get("model_reasoning_effort")
            if effort is not None and effort not in ALLOWED_EFFORT:
                errors.append(
                    f"custom agent {name} has unsupported effort: {effort}"
                )
            instructions = data["developer_instructions"]
            if "AGENTS.md" not in instructions:
                errors.append(f"custom agent lacks AGENTS.md precedence: {name}")
            section = ""
            for heading in (
                "## 필요할 때 사용할 스킬",
                "## 사용할 스킬",
            ):
                if heading in instructions:
                    section = instructions.split(heading, 1)[1].split(
                        "\n## ", 1
                    )[0]
                    break
            linked_skills[name] = set(
                re.findall(r"`([a-z0-9-]+)`", section)
            )
        except Exception as exc:
            errors.append(f"invalid custom agent {path.relative_to(root)}: {exc}")
    if not agent_names:
        errors.append("no project custom agents found")

    skill_names: set[str] = set()
    for path in sorted((root / ".agents/skills").glob("*/SKILL.md")):
        try:
            metadata = parse_frontmatter(path)
            name = metadata["name"]
            if name in skill_names:
                errors.append(f"duplicate skill: {name}")
            skill_names.add(name)
            if name != path.parent.name:
                errors.append(
                    f"skill name/path mismatch: {path.relative_to(root)}"
                )
            if len(path.read_text(encoding="utf-8").splitlines()) > 500:
                errors.append(f"SKILL.md >500 lines: {path.relative_to(root)}")
        except Exception as exc:
            errors.append(f"invalid skill {path.relative_to(root)}: {exc}")
    if not skill_names:
        errors.append("no project skills found")

    for agent, links in sorted(linked_skills.items()):
        for missing in sorted(links - skill_names):
            errors.append(
                f"custom agent {agent} references missing skill: {missing}"
            )
    return errors


def canonical_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (
        "src/contracts/CONTEXT_MANIFEST.json",
        "src/contracts/CONTRACT_LOCK.json",
    ):
        if not (root / relative).is_file():
            errors.append(f"canonical file missing: {relative}")
    try:
        _, files = canonical_files(root)
        for relative in files:
            if not (root / relative).is_file():
                errors.append(f"canonical file missing: {relative}")
    except Exception as exc:
        errors.append(f"cannot load canonical manifest: {exc}")
    return errors


def syntax_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted((root / "src").rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")
    for pattern in ("*.yaml", "*.yml"):
        for path in sorted((root / "src").rglob(pattern)):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"invalid YAML {path.relative_to(root)}: {exc}")
        workflows = root / ".github/workflows"
        if workflows.exists():
            for path in sorted(workflows.glob(pattern)):
                try:
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(
                        f"invalid YAML {path.relative_to(root)}: {exc}"
                    )
    return errors


def run(root: Path, script: str, label: str) -> str | None:
    result = subprocess.run(
        [sys.executable, str(root / "src/scripts" / script)],
        cwd=root,
        check=False,
    )
    return None if result.returncode == 0 else label


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--layout-only", action="store_true")
    mode.add_argument("--harness-only", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve() if args.root else project_root()

    errors = layout_errors(root)
    if args.layout_only:
        pass
    elif args.harness_only:
        errors += harness_errors(root)
        for script, label in (
            ("validate_harness_registry.py", "active harness registry failed"),
            ("validate_harness_evals.py", "harness trigger matrix failed"),
        ):
            failure = run(root, script, label)
            if failure:
                errors.append(failure)
    else:
        errors += harness_errors(root)
        errors += canonical_errors(root)
        errors += syntax_errors(root)
        for script, label in (
            ("validate_openapi.py", "OpenAPI validation failed"),
            ("validate_openapi_examples.py", "OpenAPI examples failed"),
            ("validate_harness_registry.py", "active harness registry failed"),
            ("validate_harness_evals.py", "harness trigger matrix failed"),
            ("verify_contract_lock.py", "contract lock failed"),
        ):
            failure = run(root, script, label)
            if failure:
                errors.append(failure)

    if errors:
        print("REPOSITORY VALIDATION FAILED")
        for error in errors:
            print("-", error)
        return 1
    print("REPOSITORY VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
