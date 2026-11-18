"""Odoo Sales Integration API.

External web API between client applications (customer portal, back office, service desk)
and the Odoo ERP, which is reached through its XML-RPC external API.

Run locally (from the `api/` folder):  uvicorn app.main:app --reload
Interactive documentation:              http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import ConfigError, get_settings
from .odoo import OdooError
from .routers import accounting, customers, purchase_orders, sale_orders, status, vendors

app = FastAPI(
    title="Odoo Sales Integration API",
    description="Web API exposing the sales and purchase processes of an Odoo instance.",
    version="1.0.0",
)

try:
    _origins = list(get_settings().cors_origins)
except ConfigError:  # settings are checked again (with a clear error) on the first request
    _origins = ["*"]

app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(OdooError)
async def odoo_error_handler(_: Request, exc: OdooError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


for module in (status, customers, sale_orders, accounting, vendors, purchase_orders):
    app.include_router(module.router)
