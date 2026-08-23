#!/usr/bin/env python3
"""Create a structured shared-contract change request in the integration workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from _contract_utils import project_root

TEMPLATE = """# Contract Change Request\n\n- ID: {identifier}\n- Created: {created}\n- Requesting harness: {harness}\n- Status: PROPOSED\n\n## Problem\n\n{problem}\n\n## Desired outcome\n\n{outcome}\n\n## Affected consumers and producers\n\n- Service Product:\n- Routing & Intelligence:\n- Frontend:\n- Data/Model:\n\n## Candidate contract changes\n\n- OpenAPI:\n- DBML:\n- Events:\n- Codes:\n- Shared documentation:\n\n## Compatibility and migration\n\n- Breaking: TBD\n- Adapter/deprecation needed: TBD\n- Database migration: TBD\n\n## Security, privacy and cost\n\nTBD\n\n## Required evidence\n\n- [ ] ADR\n- [ ] Updated examples\n- [ ] Consumer contract test\n- [ ] Provider contract test\n- [ ] Service QA approval\n- [ ] Routing QA approval\n- [ ] Changelog/version/lock update\n"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", required=True, choices=["service-product", "routing-intelligence", "integration"])
    parser.add_argument("--problem", required=True)
    parser.add_argument("--outcome", required=True)
    args = parser.parse_args()
    root = project_root()
    now = datetime.now(timezone.utc)
    identifier = f"CCR-{now.strftime('%Y%m%d-%H%M%S')}"
    output_dir = root / "_workspace/integration"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{identifier}.md"
    output.write_text(
        TEMPLATE.format(
            identifier=identifier,
            created=now.isoformat(timespec="seconds"),
            harness=args.harness,
            problem=args.problem,
            outcome=args.outcome,
        ),
        encoding="utf-8",
    )
    print(output.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
