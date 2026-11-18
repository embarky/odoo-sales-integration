"""Prepare the Odoo demo database for the customer portal.

Odoo's own demo data (customers, products, orders) is loaded when the database is created.
This script adds what the portal demo needs on top of it:

- partners that have sales or purchase orders are flagged as customers / vendors
  (customer_rank / supplier_rank), so that they appear in the portal;
- for a few customers, orders in every stage of the process: quotation, quotation sent,
  confirmed with a promised delivery date, delivered and invoiced, delivered and paid.

It only uses Odoo's XML-RPC API and the Python standard library. It can be run again safely:
each demo order has a unique customer reference and is not created twice.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
import xmlrpc.client
from datetime import datetime, timedelta, timezone

URL = os.getenv("ODOO_URL", "http://localhost:8069").rstrip("/")
DB = os.getenv("ODOO_DB", "saturne")
USER = os.getenv("ODOO_USER", "admin")
PASSWORD = os.getenv("ODOO_PASSWORD", "admin")

# customer -> orders to create: (stage, [(product default_code, quantity)], days until promised delivery)
SCENARIOS = {
    "Azure Interior": [
        ("quotation", [("E-COM07", 2), ("FURN_8855", 4)], 14),
        ("sent", [("FURN_7800", 3)], 10),
        ("confirmed", [("E-COM12", 12), ("E-COM07", 1)], 7),
        ("invoiced", [("FURN_8855", 6)], -10),
        ("paid", [("FURN_7800", 2), ("E-COM12", 8)], -20),
    ],
    "Wood Corner": [
        ("quotation", [("E-COM12", 20)], 21),
        ("confirmed", [("FURN_7800", 5)], 5),
        ("paid", [("E-COM07", 3)], -15),
    ],
}


def log(msg: str) -> None:
    print(f"[seed] {msg}", flush=True)


def wait_for_odoo(timeout: int = 900) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{URL}/web/health", timeout=5) as r:
                if r.status == 200:
                    break
        except OSError:
            pass
        if time.time() > deadline:
            sys.exit(f"Odoo did not start at {URL} within {timeout} s")
        log("waiting for Odoo...")
        time.sleep(5)
    while True:  # the HTTP server answers before the database is fully installed
        try:
            uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, PASSWORD, {})
            if uid:
                return
        except (OSError, xmlrpc.client.Fault):
            pass
        if time.time() > deadline:
            sys.exit(f"Could not log in to database '{DB}' as '{USER}'")
        log("waiting for the database...")
        time.sleep(5)


class Odoo:
    def __init__(self):
        self.uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, PASSWORD, {})
        self.proxy = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

    def __call__(self, model: str, method: str, *args, **kwargs):
        try:
            return self.proxy.execute_kw(DB, self.uid, PASSWORD, model, method, list(args), kwargs)
        except xmlrpc.client.Fault as fault:
            if "cannot marshal None" in fault.faultString:  # method succeeded and returned None
                return None
            raise


def odoo_datetime(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=9, minute=0, second=0) \
        .strftime("%Y-%m-%d %H:%M:%S")


def flag_partners(odoo: Odoo) -> None:
    for model, field in (("sale.order", "customer_rank"), ("purchase.order", "supplier_rank")):
        partner_ids = {o["partner_id"][0] for o in odoo(model, "search_read", [], fields=["partner_id"])}
        companies = {p["commercial_partner_id"][0] for p in
                     odoo("res.partner", "read", list(partner_ids), fields=["commercial_partner_id"])}
        todo = odoo("res.partner", "search", [("id", "in", list(partner_ids | companies)), (field, "=", 0)])
        if todo:
            odoo("res.partner", "write", todo, {field: 1})
        log(f"{len(todo)} partners flagged with {field}")


def deliver(odoo: Odoo, order_id: int) -> None:
    order = odoo("sale.order", "read", [order_id], fields=["picking_ids"])[0]
    for picking in odoo("stock.picking", "read", order["picking_ids"], fields=["state", "move_ids"]):
        if picking["state"] in ("done", "cancel"):
            continue
        for move in odoo("stock.move", "read", picking["move_ids"], fields=["product_uom_qty"]):
            odoo("stock.move", "write", [move["id"]], {"quantity": move["product_uom_qty"], "picked": True})
        # skip_sms: do not open the "send an SMS to the customer?" confirmation of stock_sms
        result = odoo("stock.picking", "button_validate", [picking["id"]], context={"skip_sms": True})
        if isinstance(result, dict):
            raise RuntimeError(f"Delivery of order {order_id} needs manual action: {result.get('res_model')}")


def invoice(odoo: Odoo, order_id: int, pay: bool) -> None:
    wizard = odoo("sale.advance.payment.inv", "create",
                  {"advance_payment_method": "delivered", "sale_order_ids": [(6, 0, [order_id])]})
    odoo("sale.advance.payment.inv", "create_invoices", [wizard])
    invoice_ids = odoo("sale.order", "read", [order_id], fields=["invoice_ids"])[0]["invoice_ids"]
    odoo("account.move", "action_post", invoice_ids)
    if pay:
        context = {"active_model": "account.move", "active_ids": invoice_ids}
        register = odoo("account.payment.register", "create", {}, context=context)
        odoo("account.payment.register", "action_create_payments", [register], context=context)


def create_orders(odoo: Odoo) -> None:
    for customer, orders in SCENARIOS.items():
        partner = odoo("res.partner", "search", [("name", "=", customer), ("is_company", "=", True)], limit=1)
        if not partner:
            log(f"customer {customer} not found, skipped")
            continue
        for number, (stage, lines, days) in enumerate(orders, start=1):
            ref = f"DEMO-{partner[0]}-{number}"
            if odoo("sale.order", "search_count", [("client_order_ref", "=", ref)]):
                continue
            order_lines = []
            for code, qty in lines:
                product = odoo("product.product", "search", [("default_code", "=", code)], limit=1)
                if product:
                    order_lines.append((0, 0, {"product_id": product[0], "product_uom_qty": qty}))
            if not order_lines:
                continue
            order_id = odoo("sale.order", "create", {
                "partner_id": partner[0],
                "client_order_ref": ref,
                "order_line": order_lines,
                "commitment_date": odoo_datetime(days),
            })
            if stage == "sent":
                odoo("sale.order", "write", [order_id], {"state": "sent"})  # as if sent by e-mail
            if stage in ("confirmed", "invoiced", "paid"):
                odoo("sale.order", "action_confirm", [order_id])
            if stage in ("invoiced", "paid"):
                deliver(odoo, order_id)
                invoice(odoo, order_id, pay=stage == "paid")
            name = odoo("sale.order", "read", [order_id], fields=["name"])[0]["name"]
            log(f"{customer}: {name} -> {stage}")


def main() -> None:
    wait_for_odoo()
    odoo = Odoo()
    flag_partners(odoo)
    create_orders(odoo)
    log("done")


if __name__ == "__main__":
    main()
