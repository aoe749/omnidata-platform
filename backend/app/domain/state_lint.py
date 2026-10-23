"""Static validation of the state machines declared in ``state_machines``.

Rules (each failure is reported with its rule id):

  R1  every transition references declared states
  R2  the initial state is declared and not terminal
  R3  every state is reachable from the initial state
  R4  every non-terminal state has an outgoing transition (no dead ends)
  R5  terminal states have no outgoing transitions
  R6  every in-flight state has a *sweeper* transition (stranded rows can recover)
  R7  every actor resolves to a real callable
  R8  every actor's source mentions the state it writes (each state has a writer)
  R9  the SQL CHECK constraint lists exactly the declared states
  R10 no duplicate (source, target, actor) transitions

Run ``python scripts/lint_state_machines.py`` locally or in CI; exit code 1 on error.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.state_machines import ALL_MACHINES, MachineSpec

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Issue:
    machine: str
    rule: str
    message: str
    severity: str = "error"  # "error" | "warning"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.machine} {self.rule}: {self.message}"


def _resolve(actor: str) -> Any:
    module_name, _, qualname = actor.partition(":")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    return target


def _source_mentions(actor: Any, state: str) -> bool:
    source = inspect.getsource(actor)
    return re.search(rf"""['"]{re.escape(state)}['"]""", source) is not None


def _ddl_states(path: Path, table: str, column: str) -> set[str] | None:
    text = path.read_text(encoding="utf-8")
    block = re.search(
        rf"CREATE TABLE (?:IF NOT EXISTS )?(?:\w+\.)?{re.escape(table)}\s*\((.*?)\n\s*\);",
        text,
        re.S | re.I,
    )
    if not block:
        return None
    check = re.search(
        rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\(([^)]*)\)\s*\)", block.group(1), re.I
    )
    return set(re.findall(r"'([^']+)'", check.group(1))) if check else None


def lint_machine(spec: MachineSpec, repo_root: Path = REPO_ROOT) -> list[Issue]:
    issues: list[Issue] = []

    def err(rule: str, message: str, severity: str = "error") -> None:
        issues.append(Issue(spec.name, rule, message, severity))

    states = set(spec.states)

    # R1 / R10
    seen: set[tuple[str, str, str]] = set()
    for t in spec.transitions:
        for end in (t.source, t.target):
            if end not in states:
                err("R1", f"transition {t.source}->{t.target} references unknown state '{end}'")
        key = (t.source, t.target, t.actor)
        if key in seen:
            err("R10", f"duplicate transition {t.source}->{t.target} by {t.actor}")
        seen.add(key)

    # R2
    if spec.initial not in states:
        err("R2", f"initial state '{spec.initial}' is not declared")
    elif spec.initial in spec.terminal:
        err("R2", f"initial state '{spec.initial}' must not be terminal")

    # R3 reachability (breadth-first from the initial state)
    reachable, queue = {spec.initial}, deque([spec.initial])
    while queue:
        current = queue.popleft()
        for t in spec.transitions:
            if t.source == current and t.target not in reachable:
                reachable.add(t.target)
                queue.append(t.target)
    for state in sorted(states - reachable):
        err("R3", f"state '{state}' is unreachable from '{spec.initial}'")

    # R4 / R5
    outgoing = {s: [t for t in spec.transitions if t.source == s] for s in states}
    for state in sorted(states):
        if state in spec.terminal and outgoing[state]:
            err("R5", f"terminal state '{state}' has outgoing transitions")
        if state not in spec.terminal and not outgoing[state]:
            err("R4", f"non-terminal state '{state}' is a dead end (no outgoing transition)")

    # R6
    for state in spec.in_flight:
        if not any(t.kind == "sweeper" for t in outgoing.get(state, [])):
            err("R6", f"in-flight state '{state}' has no sweeper transition")

    # R7 / R8
    def check_actor(actor: str, writes: str) -> None:
        try:
            resolved = _resolve(actor)
        except (ImportError, AttributeError) as exc:
            err("R7", f"actor {actor} cannot be resolved: {exc}")
            return
        if not callable(resolved):
            err("R7", f"actor {actor} is not callable")
        elif not _source_mentions(resolved, writes):
            err("R8", f"actor {actor} never writes state '{writes}'")

    check_actor(spec.initial_actor, spec.initial)
    for t in spec.transitions:
        check_actor(t.actor, t.target)

    # R9
    if spec.ddl:
        path = repo_root / spec.ddl.path
        if not path.exists():
            err("R9", f"{spec.ddl.path} not found; SQL cross-check skipped", "warning")
        else:
            declared = _ddl_states(path, spec.ddl.table, spec.ddl.column)
            if declared is None:
                err("R9", f"no CHECK ({spec.ddl.column} IN (...)) found for {spec.ddl.table}")
            elif declared != states:
                err(
                    "R9",
                    f"{spec.ddl.table}.{spec.ddl.column} CHECK has {sorted(declared)}, "
                    f"spec declares {sorted(states)}",
                )
    return issues


def lint_all(repo_root: Path = REPO_ROOT) -> list[Issue]:
    return [issue for spec in ALL_MACHINES for issue in lint_machine(spec, repo_root)]
