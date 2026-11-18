"""FastAPI dependencies shared by all routers."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .config import ConfigError, get_settings
from .odoo import OdooClient


@lru_cache
def _client() -> OdooClient:
    return OdooClient(get_settings())


def get_odoo() -> OdooClient:
    try:
        return _client()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


Odoo = Annotated[OdooClient, Depends(get_odoo)]


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def find_one(odoo: OdooClient, model: str, domain: list, fields: list[str], what: str) -> dict:
    """search_read that must return exactly one record, otherwise 404."""
    rows = odoo.execute(model, "search_read", domain, fields=fields, limit=1)
    if not rows:
        raise not_found(what)
    return rows[0]


def m2o_id(value) -> int | None:
    """Many2one fields come back as [id, display_name] or False."""
    return value[0] if value else None


def m2o_name(value) -> str | None:
    return value[1] if value else None


def pdf_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
