import re
from pathlib import Path

from app.core.permissions import ACTION_BITS, ALL_ACTIONS, Action, Principal, Resource, combine, describe_mask, has_action


def test_action_bits_are_distinct_powers_of_two():
    values = list(ACTION_BITS.values())
    assert len(values) == len(set(values))
    assert all(v & (v - 1) == 0 for v in values)
    assert ACTION_BITS == {"read": 1, "create": 2, "update": 4, "delete": 8, "export": 16}


def test_has_action_checks_every_requested_bit():
    mask = combine(Action.READ, Action.EXPORT)
    assert has_action(mask, Action.READ)
    assert has_action(mask, Action.EXPORT)
    assert has_action(mask, Action.READ | Action.EXPORT)
    assert not has_action(mask, Action.DELETE)
    assert not has_action(mask, Action.READ | Action.DELETE)


def test_empty_mask_grants_nothing():
    assert not any(has_action(0, a) for a in Action if a.value)
    assert describe_mask(0) == []


def test_describe_mask():
    assert describe_mask(17) == ["read", "export"]
    assert describe_mask(ALL_ACTIONS) == list(ACTION_BITS)


def test_principal_can_defaults_to_denied():
    principal = Principal(1, "a@b.c", "A", "viewer", {"transactions": 1})
    assert principal.can(Resource.TRANSACTIONS, Action.READ)
    assert not principal.can(Resource.TRANSACTIONS, Action.UPDATE)
    assert not principal.can(Resource.USERS, Action.READ)  # resource not granted at all


def test_sql_seed_masks_match_python_bits():
    """db/mysql/003_seed_roles.sql writes literal masks such as ``1 | 2 | 16``; keep them in sync."""
    seed = Path(__file__).resolve().parents[2] / "db" / "mysql" / "003_seed_roles.sql"
    alias = r"(?:\s+AS\s+\w+)?"
    rows = re.findall(rf"'(\w+)'{alias},\s*'(\w+)'{alias},\s*([\d |]+?)(?:\s+AS\s+\w+)?\s*$", seed.read_text(), re.M)
    assert rows, "no permission rows parsed"
    masks = {}
    for role, resource, expr in rows:
        assert re.fullmatch(r"[\d |]+", expr)
        value = 0
        for part in expr.split("|"):
            value |= int(part)
        assert value & ~ALL_ACTIONS == 0, f"{role}/{resource} uses an undefined bit"
        masks[(role, resource)] = value
    for resource in Resource:
        assert masks[("admin", resource.value)] == ALL_ACTIONS
    assert not has_action(masks[("viewer", "transactions")], Action.EXPORT)
    assert has_action(masks[("analyst", "transactions")], Action.EXPORT)
