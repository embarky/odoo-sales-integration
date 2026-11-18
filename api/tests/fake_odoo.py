"""A small in-memory imitation of Odoo's XML-RPC API, served over real HTTP.

It reproduces the behaviours the API depends on:
- /xmlrpc/2/common (authenticate, version) and /xmlrpc/2/object (execute_kw)
- methods that return None make the server fail with "cannot marshal None"
  *after* the change was applied (like Odoo, which commits before serialising)
- UserError -> Fault code 2, MissingError message, AccessDenied -> code 3
- sale.order.action_cancel returns the cancel wizard unless disable_cancel_warning
"""
from __future__ import annotations

import copy
import threading
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

DB, LOGIN, PASSWORD, UID = "testdb", "api@example.com", "secret", 2


def user_error(msg: str) -> xmlrpc.client.Fault:
    return xmlrpc.client.Fault(2, msg)


def initial_data() -> dict:
    return {
        "res.partner": {
            1: {"id": 1, "name": "Agrolait", "customer_rank": 1, "supplier_rank": 0, "is_company": True,
                "parent_id": False, "email": "info@agrolait.com", "phone": False, "street": "Rue 1",
                "city": "Lausanne", "zip": "1000", "country_id": [43, "Switzerland"], "comment": False},
            2: {"id": 2, "name": "Agrolait, Jane Doe", "customer_rank": 1, "supplier_rank": 0, "is_company": False,
                "parent_id": [1, "Agrolait"], "email": "jane@agrolait.com", "phone": False, "street": False,
                "city": "Lausanne", "zip": False, "country_id": [43, "Switzerland"], "comment": False},
            3: {"id": 3, "name": "Demo Supplier", "customer_rank": 0, "supplier_rank": 2, "is_company": True,
                "parent_id": False, "email": False, "phone": False, "street": False, "city": False,
                "zip": False, "country_id": False, "comment": False},
            4: {"id": 4, "name": "Brandon Freeman", "customer_rank": 3, "supplier_rank": 0, "is_company": False,
                "parent_id": False, "email": False, "phone": False, "street": False, "city": False,
                "zip": False, "country_id": False, "comment": False},
        },
        "sale.order": {
            10: {"id": 10, "name": "S00010", "invoice_status": "no", "amount_untaxed": 100.0, "amount_tax": 0.0, "client_order_ref": False, "picking_ids": [], "state": "draft", "partner_id": [1, "Agrolait"],
                 "create_date": "2025-10-01 08:00:00", "date_order": "2025-10-01 08:00:00", "amount_total": 100.0,
                 "order_line": [100, 101], "invoice_ids": [], "commitment_date": False,
                 "expected_date": "2025-10-31 21:00:00", "locked": False},
            11: {"id": 11, "name": "S00011", "invoice_status": "no", "amount_untaxed": 50.0, "amount_tax": 0.0, "client_order_ref": False, "picking_ids": [], "state": "sent", "partner_id": [2, "Agrolait, Jane Doe"],
                 "create_date": "2025-10-02 08:00:00", "date_order": "2025-10-02 08:00:00", "amount_total": 50.0,
                 "order_line": [102], "invoice_ids": [], "commitment_date": False,
                 "expected_date": False, "locked": False},
            12: {"id": 12, "name": "S00012", "invoice_status": "to invoice", "amount_untaxed": 75.0, "amount_tax": 0.0, "client_order_ref": "PO-7", "picking_ids": [300], "state": "sale", "partner_id": [4, "Brandon Freeman"],
                 "create_date": "2025-10-03 08:00:00", "date_order": "2025-10-03 08:00:00", "amount_total": 75.0,
                 "order_line": [103], "invoice_ids": [500], "commitment_date": "2025-11-05 09:00:00",
                 "expected_date": "2025-11-04 09:00:00", "locked": False, "to_invoice": True},
        },
        "sale.order.line": {
            100: {"id": 100, "name": "Section A", "product_id": False, "product_uom_qty": 0.0, "price_unit": 0.0,
                  "price_total": 0.0, "display_type": "line_section"},
            101: {"id": 101, "name": "[DESK] Desk", "product_id": [7, "[DESK] Desk"], "product_uom_qty": 2.0,
                  "price_unit": 50.0, "price_total": 100.0, "display_type": False},
            102: {"id": 102, "name": "Chair", "product_id": [8, "Chair"], "product_uom_qty": 1.0,
                  "price_unit": 50.0, "price_total": 50.0, "display_type": False},
            103: {"id": 103, "name": "Lamp", "product_id": [9, "Lamp"], "product_uom_qty": 3.0,
                  "price_unit": 25.0, "price_total": 75.0, "display_type": False},
        },
        "account.move": {
            500: {"id": 500, "name": "INV/2025/00001", "invoice_date": "2025-10-04", "amount_total": 75.0,
                  "state": "posted", "payment_state": "paid"},
        },
        "sale.advance.payment.inv": {},
        "stock.picking": {
            300: {"id": 300, "name": "WH/OUT/00001", "state": "assigned", "scheduled_date": "2025-11-05 09:00:00",
                  "date_done": False, "move_ids": [400]},
        },
        "stock.move": {
            400: {"id": 400, "product_uom_qty": 3.0, "quantity": 0.0, "picked": False, "state": "assigned"},
        },
        "account.payment.register": {},
        "purchase.order": {
            20: {"id": 20, "name": "P00020", "state": "draft", "partner_id": [3, "Demo Supplier"],
                 "date_order": "2025-10-05 08:00:00", "date_planned": "2025-10-10 12:00:00", "amount_total": 300.0,
                 "order_line": [200], "mail_reminder_confirmed": False, "effective_date": False, "received": False},
            21: {"id": 21, "name": "P00021", "state": "purchase", "partner_id": [3, "Demo Supplier"],
                 "date_order": "2025-10-06 08:00:00", "date_planned": "2025-10-12 12:00:00", "amount_total": 90.0,
                 "order_line": [201], "mail_reminder_confirmed": False, "effective_date": False, "received": True},
        },
        "purchase.order.line": {
            200: {"id": 200, "name": "Steel", "product_id": [11, "Steel"], "product_qty": 10.0, "price_unit": 30.0,
                  "price_total": 300.0, "display_type": False},
            201: {"id": 201, "name": "Bolts", "product_id": [12, "Bolts"], "product_qty": 9.0, "price_unit": 10.0,
                  "price_total": 90.0, "display_type": False},
        },
        "mail.message": {},
    }


class FakeOdoo:
    def __init__(self):
        self.data = initial_data()
        self.calls: list[tuple] = []

    # ---------------------------------------------------------------- domain
    def _children(self, ids):
        result = set(ids)
        for p in self.data["res.partner"].values():
            if p["parent_id"] and p["parent_id"][0] in ids:
                result.add(p["id"])
        return result

    def _match(self, rec, domain):
        for field, op, value in domain:
            cur = rec.get(field)
            if isinstance(cur, list) and field != "order_line":  # many2one
                cur = cur[0]
            if op == "=" and not cur == value:
                return False
            if op == ">" and not (cur or 0) > value:
                return False
            if op == "in" and cur not in value:
                return False
            if op == "ilike" and str(value).lower() not in str(cur).lower():
                return False
            if op == "child_of" and cur not in self._children(value):
                return False
        return True

    def _records(self, model, ids):
        table = self.data[model]
        missing = [i for i in ids if i not in table]
        if missing:
            raise user_error(f"Record does not exist or has been deleted.\n(Record: {model}({missing[0]},), User: 2)")
        return [table[i] for i in ids]

    @staticmethod
    def _fields(rec, fields):
        if not fields:
            return copy.deepcopy(rec)
        out = {"id": rec["id"]}
        for f in fields:
            if f not in rec:
                raise xmlrpc.client.Fault(1, f"Traceback...\nValueError: Invalid field '{f}'")
            out[f] = copy.deepcopy(rec[f])
        return out

    # ---------------------------------------------------------------- dispatch
    def execute_kw(self, db, uid, password, model, method, args, kwargs=None):
        kwargs = kwargs or {}
        if db != DB or uid != UID or password != PASSWORD:
            raise xmlrpc.client.Fault(3, "Access Denied")
        self.calls.append((model, method, args, kwargs))
        fn = getattr(self, f"m_{method}", None)
        if fn is None:
            raise xmlrpc.client.Fault(1, f"Traceback...\nAttributeError: '{model}' has no method {method}")
        return fn(model, *args, **kwargs)

    def m_search(self, model, domain, **kw):
        return [r["id"] for r in self.data[model].values() if self._match(r, domain)]

    def m_search_count(self, model, domain, **kw):
        return len(self.m_search(model, domain))

    def m_search_read(self, model, domain, fields=None, limit=None, order=None, **kw):
        rows = [self._fields(r, fields) for r in self.data[model].values() if self._match(r, domain)]
        if order:
            key, _, direction = order.partition(" ")
            rows.sort(key=lambda r: self.data[model][r["id"]].get(key) or "", reverse=direction == "desc")
        return rows[:limit] if limit else rows

    def m_read(self, model, ids, fields=None, **kw):
        if isinstance(ids, int):
            ids = [ids]
        return [self._fields(r, fields) for r in self._records(model, ids)]

    def m_write(self, model, ids, vals, **kw):
        for r in self._records(model, ids):
            r.update(vals)
        return True

    def m_create(self, model, vals, context=None, **kw):
        table = self.data[model]
        new_id = max(table, default=0) + 1
        table[new_id] = {"id": new_id, **vals, "_context": context or {}}
        return new_id

    # stock
    def m_button_validate(self, model, ids, context=None, **kw):
        for p in self._records(model, ids):
            moves = self._records("stock.move", p["move_ids"])
            if not all(m["picked"] for m in moves):
                return {"type": "ir.actions.act_window", "res_model": "stock.backorder.confirmation"}
            p["state"], p["date_done"] = "done", "2025-11-05 10:00:00"
        return True

    # accounting
    def m_action_post(self, model, ids, **kw):
        for r in self._records(model, ids):
            r["state"] = "posted"
            r["name"] = r["name"] or f"INV/2025/{r['id']:05d}"
        return False

    def m_action_create_payments(self, model, ids, context=None, **kw):
        wizard = self._records(model, ids)[0]
        for inv in self._records("account.move", wizard["_context"]["active_ids"]):
            inv["payment_state"] = "paid"
        return True

    def m_unlink(self, model, ids, **kw):
        for r in self._records(model, ids):
            del self.data[model][r["id"]]
            if model == "sale.order.line":
                for so in self.data["sale.order"].values():
                    if r["id"] in so["order_line"]:
                        so["order_line"].remove(r["id"])
        return True

    def m_message_post(self, model, ids, body="", **kw):
        self._records(model, ids)
        return self.m_create("mail.message", {"model": model, "res_id": ids[0], "body": body})

    # sale.order
    def m_action_confirm(self, model, ids, **kw):
        for r in self._records(model, ids):
            if r["state"] not in ("draft", "sent"):
                raise user_error("Some orders are not in a state requiring confirmation.")
            r["state"] = "sale"
        return True

    def m_action_cancel(self, model, ids, context=None, **kw):
        recs = self._records(model, ids)
        if any(r["locked"] for r in recs):
            raise user_error("You cannot cancel a locked order.")
        if not (context or {}).get("disable_cancel_warning") and any(r["state"] != "draft" for r in recs):
            return {"type": "ir.actions.act_window", "res_model": "sale.order.cancel"}
        for r in recs:
            r["state"] = "cancel"
        return True

    def m_create_invoices(self, model, ids, **kw):
        wizard = self._records(model, ids)[0]
        so = self.data["sale.order"][wizard["sale_order_ids"][0][2][0]]
        if not so.get("to_invoice"):
            raise user_error("There is no invoiceable line.")
        inv_id = self.m_create("account.move", {"name": False, "invoice_date": False, "state": "draft",
                                                "amount_total": so["amount_total"], "payment_state": "not_paid"})
        so["invoice_ids"].append(inv_id)
        so["to_invoice"] = False
        return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": inv_id}

    # purchase.order
    def m_button_confirm(self, model, ids, **kw):
        for r in self._records(model, ids):
            if r["state"] in ("draft", "sent"):
                r["state"] = "purchase"
        return True

    def m_button_cancel(self, model, ids, **kw):
        for r in self._records(model, ids):
            if r["received"]:
                raise user_error("Unable to cancel this purchase order. You must first cancel the related receipts.")
            r["state"] = "cancel"
        return None  # like Odoo: XML-RPC cannot marshal it

    def m_confirm_reminder_mail(self, model, ids, **kw):
        for r in self._records(model, ids):
            r["mail_reminder_confirmed"] = True
        return None


class _Handler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/xmlrpc/2/common", "/xmlrpc/2/object")

    def log_message(self, *args):  # keep test output quiet
        pass


def start_server() -> tuple[SimpleXMLRPCServer, FakeOdoo, str]:
    fake = FakeOdoo()
    server = SimpleXMLRPCServer(("127.0.0.1", 0), requestHandler=_Handler, logRequests=False, allow_none=False)
    server.register_function(
        lambda db, login, pw, ctx: UID if (db, login, pw) == (DB, LOGIN, PASSWORD) else False, "authenticate")
    server.register_function(lambda: {"server_version": "18.0+e", "protocol_version": 1}, "version")
    server.register_function(fake.execute_kw, "execute_kw")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, fake, f"http://127.0.0.1:{server.server_address[1]}"
