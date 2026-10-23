#!/usr/bin/env python
"""CLI wrapper: validate every declared state machine against code and SQL.

    python scripts/lint_state_machines.py

Exit status: 0 = clean (warnings allowed), 1 = at least one error.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Importing the repositories pulls in settings-free modules only, but keep the
# lint runnable on a bare checkout.
for key in ("JWT_SECRET", "DEMO_PASSWORD", "MSSQL_PASSWORD", "POSTGRES_PASSWORD", "MYSQL_PASSWORD"):
    os.environ.setdefault(key, "lint-only-placeholder-value-0123456789")

from app.domain.state_lint import lint_all  # noqa: E402
from app.domain.state_machines import ALL_MACHINES  # noqa: E402


def main() -> int:
    issues = lint_all()
    for issue in issues:
        print(issue)
    errors = [i for i in issues if i.severity == "error"]
    summary = f"{len(ALL_MACHINES)} state machines checked, {len(errors)} error(s), {len(issues) - len(errors)} warning(s)"
    print(("FAILED: " if errors else "OK: ") + summary)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
