"""Thin client around Odoo's external API (XML-RPC) and its PDF report URLs.

Every route uses this class instead of talking to xmlrpc.client directly, so that
connection handling, timeouts and error translation live in a single place.
"""
from __future__ import annotations

import http.client
import ssl
import threading
import xmlrpc.client
from typing import Any

import requests

from .config import Settings

# Odoo serialises the return value of a method *after* the transaction has been
# committed. Methods that return None (button_cancel, confirm_reminder_mail, ...)
# therefore succeed, but the XML-RPC answer fails with this message.
_NONE_MARSHAL = "cannot marshal None"

# Fault codes used by Odoo's /xmlrpc/2 endpoint (odoo.service.common)
_FAULT_WARNING = 2  # UserError, ValidationError, MissingError, ...
_FAULT_ACCESS_DENIED = 3
_FAULT_ACCESS_ERROR = 4


class OdooError(Exception):
    """An error that is turned into an HTTP response by the app's exception handler."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown Odoo error"


def fault_to_error(fault: xmlrpc.client.Fault) -> OdooError:
    """Translate an Odoo XML-RPC fault into an HTTP status and a readable message."""
    text = str(fault.faultString or "")
    code = fault.faultCode
    if "does not exist or has been deleted" in text:
        return OdooError(404, text.strip().splitlines()[0])
    if code == _FAULT_ACCESS_DENIED or "AccessDenied" in text:
        return OdooError(502, "Odoo rejected the API credentials")
    if code == _FAULT_ACCESS_ERROR:
        return OdooError(403, text.strip())
    if code == _FAULT_WARNING:
        return OdooError(409, text.strip())
    return OdooError(502, f"Odoo error: {_last_line(text)}")


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> http.client.HTTPConnection:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _SafeTimeoutTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float, context: ssl.SSLContext):
        super().__init__(context=context)
        self._timeout = timeout

    def make_connection(self, host: Any) -> http.client.HTTPConnection:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class OdooClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._uid: int | None = None
        self._lock = threading.Lock()
        if settings.odoo_verify_ssl:
            self._ssl = ssl.create_default_context()
        else:  # only for self-signed test servers
            self._ssl = ssl._create_unverified_context()

    # ------------------------------------------------------------------ XML-RPC
    def _proxy(self, service: str) -> xmlrpc.client.ServerProxy:
        url = f"{self.settings.odoo_url}/xmlrpc/2/{service}"
        if url.startswith("https://"):
            transport: xmlrpc.client.Transport = _SafeTimeoutTransport(self.settings.odoo_timeout, self._ssl)
        else:
            transport = _TimeoutTransport(self.settings.odoo_timeout)
        # A new proxy per call: ServerProxy objects are not thread-safe.
        return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)

    @staticmethod
    def _call(fn, *args: Any) -> Any:
        try:
            return fn(*args)
        except xmlrpc.client.Fault as fault:
            if _NONE_MARSHAL in str(fault.faultString):
                return None
            raise fault_to_error(fault) from fault
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            raise OdooError(503, f"Odoo server unreachable: {exc}") from exc

    @property
    def uid(self) -> int:
        if self._uid is None:
            with self._lock:
                if self._uid is None:
                    s = self.settings
                    uid = self._call(self._proxy("common").authenticate, s.odoo_db, s.odoo_user, s.odoo_password, {})
                    if not uid:
                        raise OdooError(502, "Odoo rejected the API credentials")
                    self._uid = int(uid)
        return self._uid

    def version(self) -> dict[str, Any]:
        return self._call(self._proxy("common").version)

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """execute_kw(model, method, args, kwargs). Methods returning None give None."""
        s = self.settings
        try:
            return self._call(
                self._proxy("object").execute_kw,
                s.odoo_db, self.uid, s.odoo_password, model, method, list(args), kwargs,
            )
        except OdooError as err:
            if err.status_code == 502 and "credentials" in err.detail:
                self._uid = None  # password changed: authenticate again next time
            raise

    # ------------------------------------------------------------------ reports
    def fetch_report_pdf(self, report_name: str, record_id: int) -> bytes:
        """Download a QWeb PDF report. Reports are not exposed through XML-RPC,
        so we open an authenticated web session, like a browser would."""
        s = self.settings
        timeout = s.odoo_timeout
        try:
            with requests.Session() as session:
                login = session.post(
                    f"{s.odoo_url}/web/session/authenticate",
                    json={"jsonrpc": "2.0", "method": "call",
                          "params": {"db": s.odoo_db, "login": s.odoo_user, "password": s.odoo_password}},
                    timeout=timeout,
                    verify=s.odoo_verify_ssl,
                )
                body = login.json() if login.headers.get("content-type", "").startswith("application/json") else {}
                if login.status_code != 200 or "error" in body or not body.get("result"):
                    raise OdooError(502, "Could not open an Odoo web session for the PDF report")
                pdf = session.get(f"{s.odoo_url}/report/pdf/{report_name}/{record_id}", timeout=timeout,
                                  verify=s.odoo_verify_ssl)
        except requests.RequestException as exc:
            raise OdooError(503, f"Odoo server unreachable: {exc}") from exc
        # Odoo answers with an HTML error page (sometimes with status 200) when the report fails.
        if pdf.status_code != 200 or not pdf.headers.get("content-type", "").startswith("application/pdf"):
            raise OdooError(502, f"Odoo did not return a PDF (HTTP {pdf.status_code})")
        return pdf.content
