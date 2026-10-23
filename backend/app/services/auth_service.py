"""Authentication and authorisation (identity in MySQL, bitmask permissions)."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.permissions import ACTION_BITS, Principal
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.engines import DatabaseRegistry, session_scope
from app.repositories.mysql_repo import UserRepository
from app.schemas.models import LoginResponse, UserProfile

log = logging.getLogger(__name__)

# Verified against when the e-mail is unknown, so response time does not reveal which accounts exist.
_DUMMY_HASH = hash_password("not-a-real-password")

DEMO_USERS: tuple[tuple[str, str, str], ...] = (
    ("admin@omnidata.example", "Ada Admin", "admin"),
    ("operator@omnidata.example", "Oscar Operator", "operator"),
    ("analyst@omnidata.example", "Anna Analyst", "analyst"),
    ("viewer@omnidata.example", "Victor Viewer", "viewer"),
)


class AuthError(Exception):
    """Credentials or token rejected (maps to HTTP 401)."""


class AuthService:
    def __init__(self, registry: DatabaseRegistry, settings: Settings) -> None:
        self._engine = registry.mysql
        self._settings = settings

    def login(self, email: str, password: str) -> LoginResponse:
        with session_scope(self._engine) as session:
            repo = UserRepository(session)
            creds = repo.find_credentials(email)
            valid = verify_password(password, creds["password_hash"] if creds else _DUMMY_HASH)
            if not creds or not valid or not creds["is_active"]:
                if creds:
                    repo.record_failed_login(creds["id"])
                raise AuthError("Invalid e-mail or password")
            repo.touch_login(creds["id"])
            user_id = int(creds["id"])
        principal = self.load_principal(user_id)
        token = create_access_token(
            subject=str(user_id),
            secret=self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
            minutes=self._settings.access_token_minutes,
        )
        return LoginResponse(access_token=token, profile=self.profile(principal))

    def principal_from_token(self, token: str) -> Principal:
        try:
            subject = decode_access_token(
                token,
                secret=self._settings.jwt_secret.get_secret_value(),
                algorithm=self._settings.jwt_algorithm,
            )
            return self.load_principal(int(subject))
        except (InvalidTokenError, ValueError) as exc:
            raise AuthError("Invalid or expired token") from exc

    def load_principal(self, user_id: int) -> Principal:
        """Permissions are read from MySQL on every request, so changes apply immediately."""
        with session_scope(self._engine) as session:
            rows = UserRepository(session).load_principal_rows(user_id)
        if not rows or not rows[0]["is_active"]:
            raise AuthError("Account not found or disabled")
        first = rows[0]
        return Principal(
            user_id=int(first["id"]),
            email=first["email"],
            full_name=first["full_name"],
            role=first["role"],
            permissions={r["resource"]: int(r["mask"]) for r in rows if r["resource"] is not None},
        )

    @staticmethod
    def profile(principal: Principal) -> UserProfile:
        return UserProfile(
            id=principal.user_id,
            email=principal.email,
            full_name=principal.full_name,
            role=principal.role,
            permissions=principal.permissions,
            action_bits=ACTION_BITS,
        )

    def seed_demo_users(self) -> int:
        """Create the demo accounts when the user table is empty. Returns the number created."""
        password = self._settings.demo_password.get_secret_value()
        with session_scope(self._engine) as session:
            repo = UserRepository(session)
            if repo.count_users() > 0:
                return 0
            created = sum(
                repo.create_user(
                    email=email, password_hash=hash_password(password), full_name=name, role=role
                )
                for email, name, role in DEMO_USERS
            )
        log.info("Seeded %d demo users", created)
        return created
