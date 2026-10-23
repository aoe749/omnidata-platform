from app.repositories.query_builder import WhereBuilder, like_pattern, order_by

ALLOWED = {"id": "id", "name": "lower(name)"}


def test_like_pattern_escapes_wildcards():
    assert like_pattern("50%_off\\") == "%50\\%\\_off\\\\%"


def test_where_builder():
    where = WhereBuilder()
    assert where.sql == ""
    where.add("a = :a", a=1)
    where.add("b > :b", b=2)
    assert where.sql == "WHERE a = :a AND b > :b"
    assert where.params == {"a": 1, "b": 2}


def test_order_by_uses_allow_list_only():
    assert order_by("name", "desc", ALLOWED, default="id", tiebreak="id") == "lower(name) DESC, id DESC"
    # Injection attempts and unknown columns fall back to the default column.
    assert order_by("id; DROP TABLE x", "asc", ALLOWED, default="id", tiebreak="id") == "id ASC, id ASC"
    assert order_by(None, "bogus", ALLOWED, default="id", tiebreak="id").startswith("id ASC")
