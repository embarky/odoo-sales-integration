import xmlrpc.client

import pytest
import requests
from fastapi.testclient import TestClient

from app import config
from app.config import Settings
from app.odoo import OdooClient, OdooError, fault_to_error
from app.timeutils import odoo_to_local, parse_user_datetime, to_odoo


# ---------------------------------------------------------------- errors
@pytest.mark.parametrize("code,text,status", [
    (2, "Record does not exist or has been deleted.\n(Record: sale.order(9,), User: 2)", 404),
    (2, "There is no invoiceable line.", 409),
    (3, "Access Denied", 502),
    (4, "You are not allowed to modify this document", 403),
    (1, "Traceback (most recent call last):\n  ...\nValueError: Invalid field 'foo'", 502),
])
def test_fault_mapping(code, text, status):
    err = fault_to_error(xmlrpc.client.Fault(code, text))
    assert err.status_code == status
    if code == 1:
        assert err.detail == "Odoo error: ValueError: Invalid field 'foo'"


# ---------------------------------------------------------------- time
def test_time_conversions():
    assert odoo_to_local("2025-01-15 12:00:00", "Europe/Zurich") == "2025-01-15 13:00:00"
    assert odoo_to_local(False, "Europe/Zurich") is None
    dt = parse_user_datetime("2025-01-15%2013%3A00", "Europe/Zurich")
    assert to_odoo(dt) == "2025-01-15 12:00:00"
    assert to_odoo(parse_user_datetime("2025-01-15T13:00:00+00:00", "Europe/Zurich")) == "2025-01-15 13:00:00"
    for bad in ("", "undefined", "null", "31.12.2025"):
        with pytest.raises(ValueError):
            parse_user_datetime(bad, "Europe/Zurich")


# ---------------------------------------------------------------- config
def test_missing_settings_give_clear_500(monkeypatch):
    from app import dependencies
    from app.main import app
    for name in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    dependencies._client.cache_clear()
    try:
        r = TestClient(app).get("/customers/all")
    finally:
        config.get_settings.cache_clear()
        dependencies._client.cache_clear()
    assert r.status_code == 500 and "ODOO_PASSWORD" in r.json()["detail"]


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "db")
    monkeypatch.setenv("ODOO_USER", "u")
    monkeypatch.setenv("ODOO_PASSWORD", "p")
    monkeypatch.setenv("ODOO_VERIFY_SSL", "false")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:1880, http://127.0.0.1:1880")
    config.get_settings.cache_clear()
    try:
        s = config.get_settings()
    finally:
        config.get_settings.cache_clear()
    assert s.odoo_url == "https://example.odoo.com" and s.odoo_verify_ssl is False
    assert s.cors_origins == ("http://localhost:1880", "http://127.0.0.1:1880")


# ---------------------------------------------------------------- PDF download
class _Resp:
    def __init__(self, status, ctype, json_body=None, content=b""):
        self.status_code, self.headers, self._json, self.content = status, {"content-type": ctype}, json_body, content

    def json(self):
        return self._json


class _Session:
    def __init__(self, login, pdf):
        self._login, self._pdf, self.urls = login, pdf, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self.urls.append(url)
        return self._login

    def get(self, url, **kw):
        self.urls.append(url)
        if isinstance(self._pdf, Exception):
            raise self._pdf
        return self._pdf


def _client():
    return OdooClient(Settings(odoo_url="https://x.odoo.com", odoo_db="db", odoo_user="u", odoo_password="p"))


def test_fetch_report_ok(monkeypatch):
    session = _Session(_Resp(200, "application/json", {"result": {"uid": 2}}),
                       _Resp(200, "application/pdf", content=b"%PDF"))
    monkeypatch.setattr(requests, "Session", lambda: session)
    assert _client().fetch_report_pdf("sale.report_saleorder", 7) == b"%PDF"
    assert session.urls[-1] == "https://x.odoo.com/report/pdf/sale.report_saleorder/7"


@pytest.mark.parametrize("login,pdf,status", [
    (_Resp(200, "application/json", {"error": {"message": "bad"}}), None, 502),         # login refused
    (_Resp(200, "application/json", {"result": {"uid": 2}}), _Resp(200, "text/html"), 502),  # HTML error page
    (_Resp(200, "application/json", {"result": {"uid": 2}}), _Resp(404, "text/html"), 502),
    (_Resp(200, "application/json", {"result": {"uid": 2}}), requests.ConnectionError("down"), 503),
])
def test_fetch_report_errors(monkeypatch, login, pdf, status):
    monkeypatch.setattr(requests, "Session", lambda: _Session(login, pdf))
    with pytest.raises(OdooError) as exc:
        _client().fetch_report_pdf("sale.report_saleorder", 7)
    assert exc.value.status_code == status
