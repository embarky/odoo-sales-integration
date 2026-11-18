"""End-to-end tests: FastAPI app -> real XML-RPC transport -> fake Odoo server."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_odoo
from app.main import app
from app.odoo import OdooClient

from .fake_odoo import DB, LOGIN


# ---------------------------------------------------------------- status & auth
def test_status(client):
    r = client.get("/get-status")
    assert r.status_code == 200
    assert r.json()["server_version"] == "18.0+e" and r.json()["uid"] == 2


def test_wrong_password_gives_502(odoo_server):
    _, url = odoo_server
    bad = OdooClient(Settings(odoo_url=url, odoo_db=DB, odoo_user=LOGIN, odoo_password="wrong", odoo_timeout=5))
    app.dependency_overrides[get_odoo] = lambda: bad
    try:
        r = TestClient(app).get("/customers/all")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 502 and "credentials" in r.json()["detail"]


def test_unreachable_server_gives_503():
    dead = OdooClient(Settings(odoo_url="http://127.0.0.1:9", odoo_db=DB, odoo_user=LOGIN,
                               odoo_password="x", odoo_timeout=2))
    app.dependency_overrides[get_odoo] = lambda: dead
    try:
        r = TestClient(app).get("/customers/all")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503


# ---------------------------------------------------------------- customers
def test_customers(client):
    assert client.get("/customers/all").json() == [
        {"value": 1, "label": "Agrolait"}, {"value": 2, "label": "Agrolait, Jane Doe"},
        {"value": 4, "label": "Brandon Freeman"}]
    assert client.get("/customers/companies").json() == [{"value": 1, "label": "Agrolait"}]
    detail = client.get("/customers/1").json()
    assert isinstance(detail, list) and detail[0]["email"] == "info@agrolait.com"
    assert client.get("/customers/999").status_code == 404
    assert client.get("/customers/abc").status_code == 422


# ---------------------------------------------------------------- sale orders: read
def test_orders_by_name_include_contacts_and_skip_sections(client):
    orders = client.get("/saleorders/by_name/agrolait").json()
    assert [o["name"] for o in orders] == ["S00011", "S00010"]  # newest first, contact's order included
    s10 = orders[1]
    assert [line["name"] for line in s10["order_line"]] == ["[DESK] Desk"]  # section line skipped
    assert s10["order_line"][0]["product_uom_qty"] == 2.0
    assert client.get("/saleorders/by_name/nobody").json() == []


def test_orders_by_customer_id(client):
    assert [o["name"] for o in client.get("/saleorders/by_id/1").json()] == ["S00011", "S00010"]
    assert client.get("/saleorders/by_id/4").json()[0]["order_line"][0]["price_total"] == 75.0
    assert client.get("/saleorders/by_id/999").json() == []


def test_order_detail(client):
    order = client.get("/saleorders/by_orderid/10").json()
    assert order["name"] == "S00010"
    assert order["order_line"] == [{"line_id": 101, "product_id": 7, "product_name": "[DESK] Desk",
                                    "description": "[DESK] Desk", "quantity": 2.0, "unit_price": 50.0, "total": 100.0}]
    assert client.get("/saleorders/by_orderid/999").status_code == 404


# ---------------------------------------------------------------- sale orders: actions
def test_confirm_quotation(client, fake):
    r = client.put("/saleorders/quotations/confirm/S00010")
    assert r.status_code == 200 and r.json()["state"] == "sale" and r.json()["ids"] == [10]
    assert client.put("/saleorders/quotations/confirm/S00010").status_code == 409  # already confirmed
    assert client.put("/saleorders/quotations/confirm/S99999").status_code == 404


def test_cancel_sent_quotation_uses_disable_cancel_warning(client, fake):
    r = client.put("/saleorders/quotations/cancel/S00011")  # 'sent' would open the wizard without the context
    assert r.status_code == 200 and fake.data["sale.order"][11]["state"] == "cancel"
    assert client.put("/saleorders/quotations/cancel/S00011").status_code == 409


def test_cancel_locked_order_returns_odoo_message(client, fake):
    fake.data["sale.order"][12]["locked"] = True
    r = client.put("/saleorders/quotations/cancel/S00012")
    assert r.status_code == 409 and "locked" in r.json()["detail"]


def test_create_invoice(client, fake):
    assert client.post("/saleorders/invoice/create/S00010").status_code == 409  # not confirmed
    r = client.post("/saleorders/invoice/create/S00012")
    assert r.status_code == 200
    inv = r.json()["invoice"]
    assert inv["id"] == 501 and inv["state"] == "draft"
    r2 = client.post("/saleorders/invoice/create/S00012")  # nothing left to invoice -> Odoo UserError
    assert r2.status_code == 409 and "invoiceable" in r2.json()["detail"]


# ---------------------------------------------------------------- delivery date
def test_query_delivery_date_both_spellings(client):
    for path in ("/saleorders/delivery_date/query/S00012", "/saleorders/delivery_date/querry/S00012"):
        body = client.get(path).json()
        assert body["scheduled_delivery_date"] == "2025-11-05 10:00:00"  # 09:00 UTC = 10:00 CET
    assert client.get("/saleorders/delivery_date/query/S00010").json()["scheduled_delivery_date"] == \
        "2025-10-31 22:00:00"  # falls back to expected_date
    assert client.get("/saleorders/delivery_date/query/S00011").json()["scheduled_delivery_date"] is None


def test_accept_delivery_date_with_or_without_date(client, fake):
    for path in ("/saleorders/delivery_date/confirm/S00012/accept",
                 "/saleorders/delivery_date/confirm/S00012/accept/undefined"):  # what the dashboard sends
        r = client.put(path)
        assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert fake.data["sale.order"][12]["commitment_date"] == "2025-11-05 09:00:00"  # unchanged
    assert len(fake.data["mail.message"]) == 2


def test_reject_delivery_date_converts_local_time_to_utc(client, fake):
    r = client.put("/saleorders/delivery_date/confirm/S00012/reject/2025-12-01%2015%3A30")
    assert r.status_code == 200, r.text
    assert r.json()["new_commitment_date"] == "2025-12-01 15:30:00"
    assert fake.data["sale.order"][12]["commitment_date"] == "2025-12-01 14:30:00"  # stored in UTC
    r = client.put("/saleorders/delivery_date/confirm/S00012/reject/2025-07-01T15:30:00")  # summer time
    assert fake.data["sale.order"][12]["commitment_date"] == "2025-07-01 13:30:00"


def test_reject_delivery_date_validation(client):
    assert client.put("/saleorders/delivery_date/confirm/S00012/reject").status_code == 422
    assert client.put("/saleorders/delivery_date/confirm/S00012/reject/undefined").status_code == 422
    assert client.put("/saleorders/delivery_date/confirm/S00012/reject/not-a-date").status_code == 422
    assert client.put("/saleorders/delivery_date/confirm/S00012/maybe").status_code == 422
    assert client.put("/saleorders/delivery_date/confirm/S99999/accept").status_code == 404


# ---------------------------------------------------------------- accounting
def test_invoices_of_order(client):
    body = client.get("/accounting/invoice/by_saleorder/S00012").json()
    assert body["sale_order_id"] == 12 and body["invoice"][0]["name"] == "INV/2025/00001"
    assert client.get("/accounting/invoice/by_saleorder/S00010").json()["invoice"] == []
    assert client.get("/accounting/invoice/by_saleorder/S99999").status_code == 404


def test_pdf_endpoints(client, odoo_client, monkeypatch):
    calls = []

    def fake_report(report, rec_id):
        calls.append((report, rec_id))
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(odoo_client, "fetch_report_pdf", fake_report)
    r = client.get("/accounting/invoice/get/pdf/500")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="invoice_500.pdf"' in r.headers["content-disposition"]
    assert client.get("/saleorders/get/pdf/10").status_code == 200
    assert client.get("/purchaseorders/get/pdf/20").status_code == 200
    assert calls == [("account.report_invoice_with_payments", 500), ("sale.report_saleorder", 10),
                     ("purchase.report_purchaseorder", 20)]
    assert client.get("/accounting/invoice/get/pdf/999").status_code == 404


# ---------------------------------------------------------------- vendors & purchase orders
def test_vendors_and_purchase_orders(client):
    assert client.get("/vendors/all").json() == [{"value": 3, "label": "Demo Supplier"}]
    pos = client.get("/purchaseorders/by_vendor_id/3").json()
    assert [p["name"] for p in pos] == ["P00021", "P00020"]
    po = client.get("/purchaseorders/by_id/20").json()
    assert po["expected_arrival"] == "2025-10-10 14:00:00" and po["arrival_confirmed"] is False
    line = po["order_line"][0]
    assert line["product_uom_qty"] == 10.0 and line["product_name"] == "Steel"
    assert client.get("/purchaseorders/by_id/999").status_code == 404


def test_purchase_confirm_and_cancel(client, fake):
    assert client.put("/purchaseorders/confirm/20").json()["state"] == "purchase"
    assert client.put("/purchaseorders/confirm/20").status_code == 409
    r = client.put("/purchaseorders/cancel/20")  # button_cancel returns None -> must still succeed
    assert r.status_code == 200 and fake.data["purchase.order"][20]["state"] == "cancel"
    r = client.put("/purchaseorders/cancel/21")  # goods received -> Odoo refuses
    assert r.status_code == 409 and "receipts" in r.json()["detail"]
    assert fake.data["purchase.order"][21]["state"] == "purchase"


def test_purchase_arrival_date(client, fake):
    for path in ("/purchaseorders/deliverdate/query/21", "/purchaseorders/deliverdate/querry/21"):
        assert client.get(path).json()["scheduled_delivery_date"] == "2025-10-12 14:00:00"
    assert client.put("/purchaseorders/deliverdate/confirm/20").status_code == 409  # not confirmed
    r = client.put("/purchaseorders/deliverdate/confirm/21")
    assert r.status_code == 200 and fake.data["purchase.order"][21]["mail_reminder_confirmed"] is True
    assert client.put("/purchaseorders/deliverdate/confirm/21").status_code == 409  # already confirmed


def test_openapi_lists_clean_paths_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/saleorders/delivery_date/query/{order_name}" in paths
    assert "/saleorders/delivery_date/querry/{order_name}" not in paths
    assert len(paths) == 28


# ---------------------------------------------------------------- quotation lines (customer portal)
def test_order_detail_has_line_ids_and_local_dates(client):
    order = client.get("/saleorders/by_orderid/12").json()
    assert order["order_line"][0]["line_id"] == 103
    assert order["scheduled_delivery_date"] == "2025-11-05 10:00:00"
    assert order["invoice_count"] == 1 and order["editable"] is False
    assert client.get("/saleorders/by_orderid/10").json()["editable"] is True


def test_update_line_quantity(client, fake):
    r = client.put("/saleorders/S00010/lines/101", json={"quantity": 5})
    assert r.status_code == 200, r.text
    assert fake.data["sale.order.line"][101]["product_uom_qty"] == 5
    assert r.json()["order_line"][0]["line_id"] == 101
    assert client.put("/saleorders/S00010/lines/101", json={"quantity": 0}).status_code == 422
    assert client.put("/saleorders/S00010/lines/100", json={"quantity": 1}).status_code == 404  # section line
    assert client.put("/saleorders/S00010/lines/103", json={"quantity": 1}).status_code == 404  # other order
    assert client.put("/saleorders/S00012/lines/103", json={"quantity": 1}).status_code == 409  # confirmed


def test_delete_line(client, fake):
    fake.data["sale.order.line"][104] = {"id": 104, "name": "Chair", "product_id": [8, "Chair"],
                                         "product_uom_qty": 1.0, "price_unit": 50.0, "price_total": 50.0,
                                         "display_type": False}
    fake.data["sale.order"][10]["order_line"].append(104)
    r = client.delete("/saleorders/S00010/lines/104")
    assert r.status_code == 200 and [line["line_id"] for line in r.json()["order_line"]] == [101]
    assert 104 not in fake.data["sale.order.line"]
    r = client.delete("/saleorders/S00010/lines/101")  # last product line
    assert r.status_code == 409 and "cancel" in r.json()["detail"]


# ---------------------------------------------------------------- order to cash (back office)
def test_deliver_invoice_and_pay(client, fake):
    order = client.get("/saleorders/by_orderid/12").json()
    assert order["delivery_state"] == "to deliver" and order["deliveries"][0]["name"] == "WH/OUT/00001"
    assert client.post("/saleorders/delivery/validate/S00010").status_code == 409  # quotation
    r = client.post("/saleorders/delivery/validate/S00012")
    assert r.status_code == 200, r.text
    assert fake.data["stock.move"][400]["quantity"] == 3.0 and fake.data["stock.picking"][300]["state"] == "done"
    assert client.get("/saleorders/by_orderid/12").json()["delivery_state"] == "delivered"
    assert client.post("/saleorders/delivery/validate/S00012").status_code == 409  # nothing left

    invoice_id = client.post("/saleorders/invoice/create/S00012").json()["invoice"]["id"]
    assert client.post(f"/accounting/invoice/{invoice_id}/pay").status_code == 409  # still a draft
    r = client.post(f"/accounting/invoice/{invoice_id}/confirm")
    assert r.status_code == 200 and r.json()["invoice"]["state"] == "posted"
    assert client.post(f"/accounting/invoice/{invoice_id}/confirm").status_code == 409
    r = client.post(f"/accounting/invoice/{invoice_id}/pay")
    assert r.status_code == 200 and r.json()["invoice"]["payment_state"] == "paid"
    assert client.post(f"/accounting/invoice/{invoice_id}/pay").status_code == 409
    assert client.post("/accounting/invoice/999/confirm").status_code == 404
