from dataclasses import replace

from app.domain.state_lint import lint_all, lint_machine
from app.domain.state_machines import ALL_MACHINES, WORK_QUEUE, Transition


def rules(issues):
    return {i.rule for i in issues if i.severity == "error"}


def test_declared_machines_are_clean():
    errors = [i for i in lint_all() if i.severity == "error"]
    assert errors == [], "\n".join(map(str, errors))


def test_ddl_cross_check_actually_ran():
    # Guard against the check silently skipping when the SQL files move.
    assert not [i for i in lint_all() if i.rule == "R9"]
    assert all(m.ddl for m in ALL_MACHINES)


def test_detects_unreachable_state():
    spec = replace(WORK_QUEUE, states=WORK_QUEUE.states + ("orphan",))
    assert {"R3", "R4"} <= rules(lint_machine(spec))


def test_detects_dead_end_state():
    spec = replace(WORK_QUEUE, transitions=tuple(t for t in WORK_QUEUE.transitions if t.target != "done"))
    assert "R3" in rules(lint_machine(spec))  # 'done' no longer reachable


def test_detects_missing_sweeper():
    spec = replace(WORK_QUEUE, transitions=tuple(t for t in WORK_QUEUE.transitions if t.kind != "sweeper"))
    assert "R6" in rules(lint_machine(spec))


def test_detects_unknown_state_and_unresolvable_actor():
    bad = Transition("queued", "nowhere", "app.repositories.postgres_repo:WorkQueueRepository.missing")
    spec = replace(WORK_QUEUE, transitions=WORK_QUEUE.transitions + (bad,))
    assert {"R1", "R7"} <= rules(lint_machine(spec))


def test_detects_actor_that_never_writes_target_state():
    wrong = Transition("processing", "done", "app.repositories.postgres_repo:WorkQueueRepository.reset_stale")
    spec = replace(WORK_QUEUE, transitions=WORK_QUEUE.transitions + (wrong,))
    assert "R8" in rules(lint_machine(spec))


def test_detects_ddl_drift(tmp_path):
    ddl = tmp_path / "db" / "postgres"
    ddl.mkdir(parents=True)
    (ddl / "001_schema.sql").write_text(
        "CREATE TABLE IF NOT EXISTS work_queue (\n  status TEXT CHECK (status IN ('queued', 'processing', 'done'))\n);"
    )
    assert "R9" in rules(lint_machine(WORK_QUEUE, repo_root=tmp_path))
