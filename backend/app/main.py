"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.deps import get_auth_service
from app.api.routes import auth, data, sync
from app.core.config import get_settings
from app.db.engines import DatabaseRegistry, get_registry
from app.schemas.models import DbHealth
from app.services.auth_service import AuthService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("omnidata")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        get_auth_service(get_registry(), get_settings()).seed_demo_users()
    except Exception:  # the API must still start so /health can report what is wrong
        log.warning("Demo user seeding skipped", exc_info=True)
    yield
    get_registry().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    api.include_router(sync.router)
    api.include_router(data.router)
    app.include_router(api)

    @app.get("/api/health", tags=["health"])
    def health(registry: DatabaseRegistry = Depends(get_registry)) -> dict[str, DbHealth]:
        """Liveness + dependency check; unauthenticated and free of sensitive detail."""
        result: dict[str, DbHealth] = {}
        for name, engine in (("mssql", registry.mssql), ("postgres", registry.postgres), ("mysql", registry.mysql)):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                result[name] = DbHealth(status="ok")
            except Exception as exc:
                result[name] = DbHealth(status="error", error=type(exc).__name__)
        return result

    return app


app = create_app()
