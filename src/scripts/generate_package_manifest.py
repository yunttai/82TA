#!/usr/bin/env python3
"""Regenerate src/docs/PACKAGE_MANIFEST.md from the current package tree."""

from __future__ import annotations

from pathlib import Path

from _contract_utils import project_root

SKIP_PARTS = {
    ".codegraph",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    ".venv",
    "__pycache__",
    "node_modules",
}


def main() -> int:
    root = project_root()
    output = root / "src/docs/PACKAGE_MANIFEST.md"
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.as_posix() == "src/docs/PACKAGE_MANIFEST.md":
            continue
        files.append(relative.as_posix())
    content = [
        "# Package Manifest",
        "",
        "이 파일은 `python src/scripts/generate_package_manifest.py`로 생성한다.",
        "",
        f"총 파일 수(이 manifest 제외): **{len(files)}**",
        "",
        "```text",
        *files,
        "```",
        "",
    ]
    output.write_text("\n".join(content), encoding="utf-8")
    print(f"updated {output.relative_to(root)} with {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
