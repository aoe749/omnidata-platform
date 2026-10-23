"""Shared request/response shapes for server-side tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class TableParams:
    page: int
    page_size: int
    sort_by: str | None
    sort_dir: Literal["asc", "desc"]

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def table_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str | None = Query(None, max_length=64),
    sort_dir: Literal["asc", "desc"] = "asc",
) -> TableParams:
    """FastAPI dependency parsing ``?page=&page_size=&sort_by=&sort_dir=``."""
    return TableParams(page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir)
