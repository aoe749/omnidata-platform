"""Declarative state machines for every persisted ``status`` / ``state`` column.

These specs are the single source of truth that ``state_lint`` checks against
the code (repository methods) and the SQL schema (CHECK constraints).

Vocabulary
----------
writer   an actor that moves rows from one state to another
sweeper  a writer that recovers rows stranded in an *in-flight* state
         (e.g. a worker crashed while holding a row)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    actor: str  # "package.module:Class.method"
    kind: str = "writer"  # "writer" | "sweeper"


@dataclass(frozen=True)
class DdlRef:
    path: str  # relative to the repository root
    table: str
    column: str


@dataclass(frozen=True)
class MachineSpec:
    name: str
    states: tuple[str, ...]
    initial: str
    initial_actor: str
    terminal: tuple[str, ...]
    in_flight: tuple[str, ...]
    transitions: tuple[Transition, ...]
    ddl: DdlRef | None = None


_PG = "app.repositories.postgres_repo:WorkQueueRepository"
_MS = "app.repositories.mssql_repo:MigrationStateRepository"

WORK_QUEUE = MachineSpec(
    name="work_queue",
    states=("queued", "processing", "done", "dead"),
    initial="queued",
    initial_actor=f"{_PG}.enqueue",
    terminal=("done", "dead"),
    in_flight=("processing",),
    transitions=(
        Transition("queued", "processing", f"{_PG}.claim_batch"),
        Transition("processing", "done", f"{_PG}.mark_done"),
        Transition("processing", "queued", f"{_PG}.mark_retry"),
        Transition("processing", "dead", f"{_PG}.mark_retry"),
        Transition("processing", "queued", f"{_PG}.reset_stale", kind="sweeper"),
    ),
    ddl=DdlRef("db/postgres/001_schema.sql", "work_queue", "status"),
)

MIGRATION_RUN = MachineSpec(
    name="migration_run",
    states=("running", "completed", "failed"),
    initial="running",
    initial_actor=f"{_MS}.create_run",
    terminal=("completed",),
    in_flight=("running",),
    transitions=(
        Transition("running", "completed", f"{_MS}.mark_completed"),
        Transition("running", "failed", f"{_MS}.mark_failed"),
        Transition("running", "failed", f"{_MS}.fail_stale", kind="sweeper"),
        Transition("failed", "running", f"{_MS}.resume"),
    ),
    ddl=DdlRef("db/mssql/001_source_and_sync.sql", "migration_runs", "state"),
)

OUTBOX = MachineSpec(
    name="outbox",
    states=("pending", "published"),
    initial="pending",
    initial_actor=f"{_MS}.insert_outbox",
    terminal=("published",),
    in_flight=(),
    transitions=(Transition("pending", "published", f"{_MS}.mark_published"),),
    ddl=DdlRef("db/mssql/001_source_and_sync.sql", "outbox", "state"),
)

ALL_MACHINES: tuple[MachineSpec, ...] = (WORK_QUEUE, MIGRATION_RUN, OUTBOX)
