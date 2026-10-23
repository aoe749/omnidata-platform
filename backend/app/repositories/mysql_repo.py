"""MySQL repositories: users, roles and per-resource permission masks."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_credentials(self, email: str) -> dict[str, Any] | None:
        row = self.session.execute(
            text("SELECT id, email, password_hash, is_active FROM users WHERE email = :email"),
            {"email": email.strip().lower()},
        ).mappings().first()
        return dict(row) if row else None

    def load_principal_rows(self, user_id: int) -> list[dict[str, Any]]:
        """One row per (user, resource) — a single join resolves identity, role and masks."""
        rows = self.session.execute(
            text(
                "SELECT u.id, u.email, u.full_name, u.is_active, r.name AS role, rp.resource, rp.mask "
                "FROM users u "
                "JOIN roles r ON r.id = u.role_id "
                "LEFT JOIN role_permissions rp ON rp.role_id = r.id "
                "WHERE u.id = :id"
            ),
            {"id": user_id},
        ).mappings()
        return [dict(r) for r in rows]

    def touch_login(self, user_id: int) -> None:
        self.session.execute(
            text("UPDATE users SET last_login_at = UTC_TIMESTAMP(), failed_logins = 0 WHERE id = :id"),
            {"id": user_id},
        )

    def record_failed_login(self, user_id: int) -> None:
        self.session.execute(
            text("UPDATE users SET failed_logins = LEAST(failed_logins + 1, 65535) WHERE id = :id"),
            {"id": user_id},
        )

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text(
                "SELECT u.id, u.email, u.full_name, r.name AS role, u.is_active, u.created_at, u.last_login_at "
                "FROM users u JOIN roles r ON r.id = u.role_id ORDER BY u.id"
            )
        ).mappings()
        return [{**dict(r), "is_active": bool(r["is_active"])} for r in rows]

    def deactivate(self, user_id: int) -> bool:
        return self.session.execute(
            text("UPDATE users SET is_active = 0 WHERE id = :id AND is_active = 1"), {"id": user_id}
        ).rowcount == 1

    def count_users(self) -> int:
        return int(self.session.execute(text("SELECT COUNT(*) FROM users")).scalar_one())

    def counts(self) -> dict[str, int]:
        row = self.session.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM users WHERE is_active = 1) AS active_users, "
                "       (SELECT COUNT(*) FROM roles) AS roles"
            )
        ).mappings().one()
        return {k: int(v) for k, v in row.items()}

    def create_user(self, *, email: str, password_hash: str, full_name: str, role: str) -> bool:
        return self.session.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, role_id) "
                "SELECT :email, :hash, :name, id FROM roles WHERE name = :role"
            ),
            {"email": email.strip().lower(), "hash": password_hash, "name": full_name, "role": role},
        ).rowcount == 1
