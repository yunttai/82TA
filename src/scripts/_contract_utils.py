#!/usr/bin/env python3
"""Shared helpers for canonical context and contract lock validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CANONICAL_TEXT_SUFFIXES = frozenset({".dbml", ".json", ".md", ".yaml", ".yml"})


def project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "src/contracts/CONTEXT_MANIFEST.json").is_file():
            return candidate
    raise RuntimeError("Project root containing src/contracts/CONTEXT_MANIFEST.json was not found")


def sha256_file(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in CANONICAL_TEXT_SUFFIXES:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"canonical text is not valid UTF-8: {path}") from exc
        # Git may materialize CRLF on Windows even though the committed blob and
        # Linux checkout use LF. Hash canonical text semantics, while unknown or
        # binary extensions remain byte-exact below.
        raw = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def canonical_files(root: Path) -> tuple[dict[str, Any], list[str]]:
    manifest_path = root / "src/contracts/CONTEXT_MANIFEST.json"
    manifest = load_json(manifest_path)
    paths = manifest.get("canonicalFiles")
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise ValueError("canonicalFiles must be a list of repository-relative strings")
    return manifest, paths


def calculate_lock(root: Path) -> dict[str, Any]:
    manifest, paths = canonical_files(root)
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for relative in paths:
        target = root / relative
        if not target.is_file():
            missing.append(relative)
            continue
        hashes[relative] = sha256_file(target)
    if missing:
        raise FileNotFoundError("Missing canonical files: " + ", ".join(missing))
    aggregate_input = "".join(f"{path}:{hashes[path]}\n" for path in sorted(hashes))
    aggregate = hashlib.sha256(aggregate_input.encode("utf-8")).hexdigest()
    return {
        "project": manifest.get("project"),
        "contextVersion": manifest.get("contextVersion"),
        "contractVersion": manifest.get("contractVersion"),
        "algorithm": "sha256",
        "files": hashes,
        "aggregateSha256": aggregate,
    }
