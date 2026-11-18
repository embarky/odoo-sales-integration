from fastapi import APIRouter, HTTPException

from ..dependencies import Odoo, find_one, m2o_id, m2o_name, not_found, pdf_response
from ..odoo import OdooClient
from ..timeutils import odoo_to_local

router = APIRouter(prefix="/purchaseorders", tags=["Purchase Orders"])

PO_FIELDS = ["name", "state", "date_order", "date_planned", "amount_total", "partner_id", "order_line"]
PO_LINE_FIELDS = ["name", "product_id", "product_qty", "price_unit", "price_total", "display_type"]


def _po(odoo: OdooClient, po_id: int, fields: list[str]) -> dict:
    return find_one(odoo, "purchase.order", [("id", "=", po_id)], fields, f"Purchase order {po_id}")


def _with_lines(odoo: OdooClient, orders: list[dict]) -> list[dict]:
    line_ids = [lid for o in orders for lid in o["order_line"]]
    lines = {}
    if line_ids:
        for line in odoo.execute("purchase.order.line", "read", line_ids, fields=PO_LINE_FIELDS):
            if not line.get("display_type"):
                lines[line["id"]] = line
    for order in orders:
        order["order_line"] = [
            {
                "id": line["id"],
                "name": line["name"],
                "description": line["name"],
                "product_id": m2o_id(line["product_id"]),
                "product_name": m2o_name(line["product_id"]),
                "product_qty": line["product_qty"],
                "product_uom_qty": line["product_qty"],  # key used by the dashboard templates
                "price_unit": line["price_unit"],
                "price_total": line["price_total"],
            }
            for lid in order["order_line"] if (line := lines.get(lid))
        ]
    return orders


def _state(odoo: OdooClient, po_id: int) -> str:
    return odoo.execute("purchase.order", "read", [po_id], fields=["state"])[0]["state"]


@router.get("/by_vendor_id/{vendor_id}")
def get_purchase_orders_by_vendor(vendor_id: int, odoo: Odoo):
    """All purchase orders (with lines) of a vendor."""
    orders = odoo.execute("purchase.order", "search_read", [("partner_id", "child_of", [vendor_id])],
                          fields=PO_FIELDS, order="date_order desc")
    return _with_lines(odoo, orders)


@router.get("/by_id/{purchase_order_id}")
def get_purchase_order(purchase_order_id: int, odoo: Odoo):
    """One purchase order with its lines, its expected arrival in local time and whether the
    vendor confirmed that date."""
    po = _po(odoo, purchase_order_id, PO_FIELDS + ["mail_reminder_confirmed", "effective_date"])
    tz = odoo.settings.timezone
    po["expected_arrival"] = odoo_to_local(po["date_planned"], tz)
    po["received_on"] = odoo_to_local(po.pop("effective_date"), tz)
    po["arrival_confirmed"] = po.pop("mail_reminder_confirmed")
    return _with_lines(odoo, [po])[0]


@router.put("/confirm/{purchase_orders_id}")
def confirm_purchase_order(purchase_orders_id: int, odoo: Odoo):
    """Confirm an RFQ (button 'Confirm Order', purchase.order.button_confirm)."""
    po = _po(odoo, purchase_orders_id, ["name", "state"])
    if po["state"] not in ("draft", "sent"):
        raise HTTPException(409, f"Purchase order {po['name']} is in state '{po['state']}' and cannot be confirmed")
    odoo.execute("purchase.order", "button_confirm", [po["id"]])
    state = _state(odoo, po["id"])
    if state not in ("purchase", "to approve"):
        raise HTTPException(409, f"Odoo did not confirm {po['name']} (state is now '{state}')")
    return {"message": "Purchase Order confirmed successfully", "purchase_orders_id": po["id"], "state": state}


@router.put("/cancel/{purchase_orders_id}")
def cancel_purchase_order(purchase_orders_id: int, odoo: Odoo):
    """Cancel a purchase order (purchase.order.button_cancel). Odoo refuses when goods were
    already received or billed; that refusal is returned as HTTP 409."""
    po = _po(odoo, purchase_orders_id, ["name", "state"])
    if po["state"] == "cancel":
        raise HTTPException(409, f"Purchase order {po['name']} is already cancelled")
    odoo.execute("purchase.order", "button_cancel", [po["id"]])
    state = _state(odoo, po["id"])
    if state != "cancel":
        raise HTTPException(409, f"Odoo did not cancel {po['name']} (state is still '{state}')")
    return {"message": "Purchase Order cancelled", "purchase_orders_id": po["id"], "state": state}


@router.get("/deliverdate/query/{purchase_orders_id}")
@router.get("/deliverdate/querry/{purchase_orders_id}", include_in_schema=False)  # old spelling used by the flows
def get_expected_arrival(purchase_orders_id: int, odoo: Odoo):
    """Expected arrival date (date_planned) in local time."""
    po = _po(odoo, purchase_orders_id, ["name", "date_planned"])
    return {
        "id": po["id"],
        "order_name": po["name"],
        "scheduled_delivery_date": odoo_to_local(po["date_planned"], odoo.settings.timezone),
    }


@router.put("/deliverdate/confirm/{purchase_orders_id}")
def confirm_expected_arrival(purchase_orders_id: int, odoo: Odoo):
    """Record that the vendor confirmed the arrival date (purchase.order.confirm_reminder_mail),
    with the same conditions as the button in Odoo."""
    po = _po(odoo, purchase_orders_id,
             ["name", "state", "mail_reminder_confirmed", "date_planned", "effective_date"])
    if po["state"] not in ("purchase", "done"):
        raise HTTPException(409, f"Purchase order {po['name']} is not confirmed")
    if po["mail_reminder_confirmed"]:
        raise HTTPException(409, f"The arrival date of {po['name']} is already confirmed")
    if not po["date_planned"] or po["effective_date"]:
        raise HTTPException(409, f"{po['name']} has no planned date or was already received")
    odoo.execute("purchase.order", "confirm_reminder_mail", [po["id"]])
    return {"status": "success", "order_id": po["id"],
            "scheduled_delivery_date": odoo_to_local(po["date_planned"], odoo.settings.timezone)}


@router.get("/get/pdf/{purchase_orders_id}")
def get_purchase_order_pdf(purchase_orders_id: int, odoo: Odoo):
    """PDF of a purchase order (report purchase.report_purchaseorder)."""
    if not odoo.execute("purchase.order", "search_count", [("id", "=", purchase_orders_id)]):
        raise not_found(f"Purchase order {purchase_orders_id}")
    content = odoo.fetch_report_pdf("purchase.report_purchaseorder", purchase_orders_id)
    return pdf_response(content, f"purchase_order_{purchase_orders_id}.pdf")
