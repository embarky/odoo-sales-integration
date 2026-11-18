from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import Odoo, find_one, m2o_id, m2o_name, not_found, pdf_response
from ..odoo import OdooClient
from ..timeutils import odoo_to_local, parse_user_datetime, to_odoo

router = APIRouter(prefix="/saleorders", tags=["Sale Orders"])

ORDER_FIELDS = ["name", "state", "create_date", "date_order", "amount_total", "partner_id", "order_line",
                "invoice_status"]
LINE_FIELDS = ["name", "product_id", "product_uom_qty", "price_unit", "price_total", "display_type"]
DETAIL_FIELDS = ORDER_FIELDS + ["commitment_date", "expected_date", "invoice_status", "invoice_ids",
                                "amount_untaxed", "amount_tax", "client_order_ref", "picking_ids"]
EDITABLE_STATES = ("draft", "sent")  # quotations; confirmed orders are changed by the company


# ---------------------------------------------------------------- helpers
def _order_by_name(odoo: OdooClient, order_name: str, fields: list[str]) -> dict:
    return find_one(odoo, "sale.order", [("name", "=", order_name)], fields, f"Order {order_name}")


def _product_lines(odoo: OdooClient, line_ids: list[int]) -> dict[int, dict]:
    """Read order lines in one call; section and note lines (no product) are skipped."""
    if not line_ids:
        return {}
    lines = odoo.execute("sale.order.line", "read", line_ids, fields=LINE_FIELDS)
    return {line["id"]: line for line in lines if not line.get("display_type")}


def _list_line(line: dict) -> dict:
    # keys expected by the "Display orders" template of the dashboard
    return {
        "id": line["id"],
        "name": line["name"],
        "product_id": m2o_id(line["product_id"]),
        "product_uom_qty": line["product_uom_qty"],
        "price_unit": line["price_unit"],
        "price_total": line["price_total"],
    }


def _orders_with_lines(odoo: OdooClient, domain: list) -> list[dict]:
    orders = odoo.execute("sale.order", "search_read", domain, fields=ORDER_FIELDS, order="date_order desc")
    lines = _product_lines(odoo, [lid for o in orders for lid in o["order_line"]])
    for order in orders:
        order["order_line"] = [_list_line(lines[lid]) for lid in order["order_line"] if lid in lines]
    return orders


# ---------------------------------------------------------------- read
@router.get("/by_name/{cust_name}")
def get_orders_by_customer_name(cust_name: str, odoo: Odoo):
    """All orders (with lines) of the customers whose name contains `cust_name`, e.g. 'Agrolait'.
    Orders placed by contacts of a company are included (child_of)."""
    partner_ids = odoo.execute("res.partner", "search", [("name", "ilike", cust_name)])
    if not partner_ids:
        return []
    return _orders_with_lines(odoo, [("partner_id", "child_of", partner_ids)])


@router.get("/by_id/{cust_id}")
def get_orders_by_customer_id(cust_id: int, odoo: Odoo):
    """All orders (with lines) of one customer and of its contacts."""
    return _orders_with_lines(odoo, [("partner_id", "child_of", [cust_id])])


@router.get("/by_orderid/{order_id}")
def get_order(order_id: int, odoo: Odoo):
    """One order with detailed lines (product, description, quantity, prices) and its delivery date
    in local time. `editable` tells whether the customer may still change the lines."""
    order = find_one(odoo, "sale.order", [("id", "=", order_id)], DETAIL_FIELDS, f"Order {order_id}")
    return _detail(odoo, order)


def _detail(odoo: OdooClient, order: dict) -> dict:
    lines = _product_lines(odoo, order["order_line"])
    tz = odoo.settings.timezone
    order["order_line"] = [
        {
            "line_id": lid,
            "product_id": m2o_id(line["product_id"]),
            "product_name": m2o_name(line["product_id"]),
            "description": line["name"],
            "quantity": line["product_uom_qty"],
            "unit_price": line["price_unit"],
            "total": line["price_total"],
        }
        for lid in order["order_line"] if (line := lines.get(lid))
    ]
    order["date_order"] = odoo_to_local(order["date_order"], tz)
    order["scheduled_delivery_date"] = odoo_to_local(order["commitment_date"] or order["expected_date"], tz)
    order["commitment_date"] = odoo_to_local(order["commitment_date"], tz)
    order["expected_date"] = odoo_to_local(order["expected_date"], tz)
    order["invoice_count"] = len(order.pop("invoice_ids"))
    order["deliveries"] = _deliveries(odoo, order.pop("picking_ids"))
    pending = [d for d in order["deliveries"] if d["state"] not in ("done", "cancel")]
    done = [d for d in order["deliveries"] if d["state"] == "done"]
    order["delivery_state"] = "to deliver" if pending else ("delivered" if done else "none")
    order["editable"] = order["state"] in EDITABLE_STATES
    return order


def _deliveries(odoo: OdooClient, picking_ids: list[int]) -> list[dict]:
    if not picking_ids:
        return []
    tz = odoo.settings.timezone
    pickings = odoo.execute("stock.picking", "read", picking_ids, fields=["name", "state", "scheduled_date", "date_done"])
    return [{"id": p["id"], "name": p["name"], "state": p["state"],
             "scheduled_date": odoo_to_local(p["scheduled_date"], tz), "date_done": odoo_to_local(p["date_done"], tz)}
            for p in pickings]


# ---------------------------------------------------------------- quotation lines
class LineUpdate(BaseModel):
    quantity: float = Field(gt=0, description="New ordered quantity")


def _editable_line(odoo: OdooClient, order_name: str, line_id: int) -> dict:
    order = _order_by_name(odoo, order_name, ["state", "order_line"])
    if line_id not in order["order_line"] or line_id not in _product_lines(odoo, [line_id]):
        raise not_found(f"Line {line_id} of order {order_name}")
    if order["state"] not in EDITABLE_STATES:
        raise HTTPException(409, f"Order {order_name} is confirmed ('{order['state']}'): "
                                 "only quotations can be changed")
    return order


def _detail_by_id(odoo: OdooClient, order_id: int) -> dict:
    return _detail(odoo, odoo.execute("sale.order", "read", [order_id], fields=DETAIL_FIELDS)[0])


@router.put("/{order_name}/lines/{line_id}")
def update_quotation_line(order_name: str, line_id: int, body: LineUpdate, odoo: Odoo):
    """Change the quantity of a product line of a quotation. Returns the updated order."""
    order = _editable_line(odoo, order_name, line_id)
    odoo.execute("sale.order.line", "write", [line_id], {"product_uom_qty": body.quantity})
    return _detail_by_id(odoo, order["id"])


@router.delete("/{order_name}/lines/{line_id}")
def delete_quotation_line(order_name: str, line_id: int, odoo: Odoo):
    """Remove a product line from a quotation. The last product line cannot be removed
    (cancel the quotation instead). Returns the updated order."""
    order = _editable_line(odoo, order_name, line_id)
    if len(_product_lines(odoo, order["order_line"])) == 1:
        raise HTTPException(409, f"This is the last product of {order_name}: cancel the quotation instead")
    odoo.execute("sale.order.line", "unlink", [line_id])
    return _detail_by_id(odoo, order["id"])


# ---------------------------------------------------------------- quotation actions
@router.put("/quotations/confirm/{order_name}")
def confirm_quotation(order_name: str, odoo: Odoo):
    """Confirm a quotation (button 'Confirm', sale.order.action_confirm): Quotation -> Sales Order."""
    order = _order_by_name(odoo, order_name, ["state"])
    if order["state"] not in ("draft", "sent"):
        raise HTTPException(409, f"Order {order_name} is in state '{order['state']}' and cannot be confirmed")
    odoo.execute("sale.order", "action_confirm", [order["id"]])
    state = odoo.execute("sale.order", "read", [order["id"]], fields=["state"])[0]["state"]
    if state != "sale":
        raise HTTPException(409, f"Odoo did not confirm {order_name} (state is now '{state}')")
    return {"message": "Order confirmed successfully", "order_name": order_name, "ids": [order["id"]], "state": state}


@router.put("/quotations/cancel/{order_name}")
def cancel_quotation(order_name: str, odoo: Odoo):
    """Cancel a quotation or order (sale.order.action_cancel).
    `disable_cancel_warning` is required: without it Odoo returns the cancel wizard
    for orders that are not in draft and nothing is cancelled."""
    order = _order_by_name(odoo, order_name, ["state"])
    if order["state"] == "cancel":
        raise HTTPException(409, f"Order {order_name} is already cancelled")
    odoo.execute("sale.order", "action_cancel", [order["id"]], context={"disable_cancel_warning": True})
    state = odoo.execute("sale.order", "read", [order["id"]], fields=["state"])[0]["state"]
    if state != "cancel":
        raise HTTPException(409, f"Odoo did not cancel {order_name} (state is still '{state}')")
    return {"message": "Order canceled successfully", "order_name": order_name, "ids": [order["id"]], "state": state}


# ---------------------------------------------------------------- delivery
@router.post("/delivery/validate/{order_name}")
def validate_delivery(order_name: str, odoo: Odoo):
    """Ship everything still open on a confirmed order: the ordered quantities are set as done
    and the delivery orders are validated (stock.picking.button_validate)."""
    order = _order_by_name(odoo, order_name, ["state", "picking_ids"])
    if order["state"] != "sale":
        raise HTTPException(409, f"Order {order_name} must be confirmed before delivery (state '{order['state']}')")
    pickings = [p for p in _deliveries(odoo, order["picking_ids"]) if p["state"] not in ("done", "cancel")]
    if not pickings:
        raise HTTPException(409, f"Nothing left to deliver for {order_name}")
    for picking in pickings:
        move_ids = odoo.execute("stock.picking", "read", [picking["id"]], fields=["move_ids"])[0]["move_ids"]
        for move in odoo.execute("stock.move", "read", move_ids, fields=["product_uom_qty", "state"]):
            if move["state"] not in ("done", "cancel"):
                odoo.execute("stock.move", "write", [move["id"]], {"quantity": move["product_uom_qty"], "picked": True})
        # skip_sms: no "send an SMS to the customer?" wizard (stock_sms)
        result = odoo.execute("stock.picking", "button_validate", [picking["id"]], context={"skip_sms": True})
        if isinstance(result, dict) and result.get("res_model"):
            raise HTTPException(409, f"Odoo asks for a manual step to validate {picking['name']} ({result['res_model']})")
    after = _deliveries(odoo, order["picking_ids"])
    if any(p["state"] not in ("done", "cancel") for p in after):
        raise HTTPException(409, f"Odoo did not complete the delivery of {order_name}")
    return {"message": f"{order_name} delivered", "order_name": order_name, "deliveries": after}


# ---------------------------------------------------------------- invoicing
@router.post("/invoice/create/{order_name}")
def create_invoice(order_name: str, odoo: Odoo):
    """Create the invoice of a confirmed order, like the 'Create Invoice' button
    (wizard sale.advance.payment.inv, option 'Regular invoice')."""
    order = _order_by_name(odoo, order_name, ["state", "invoice_ids"])
    if order["state"] != "sale":
        raise HTTPException(409, f"Order {order_name} must be confirmed before invoicing (state '{order['state']}')")
    before = set(order["invoice_ids"])
    wizard_id = odoo.execute(
        "sale.advance.payment.inv", "create",
        {"advance_payment_method": "delivered", "sale_order_ids": [(6, 0, [order["id"]])]},
    )
    odoo.execute("sale.advance.payment.inv", "create_invoices", [wizard_id])
    after = odoo.execute("sale.order", "read", [order["id"]], fields=["invoice_ids"])[0]["invoice_ids"]
    new_ids = sorted(set(after) - before)
    if not new_ids:
        raise HTTPException(409, f"No invoice was created for {order_name} (nothing left to invoice)")
    invoices = odoo.execute("account.move", "read", new_ids, fields=["id", "name", "amount_total", "state"])
    newest = max(invoices, key=lambda inv: inv["id"])
    return {
        "message": f"Invoice created successfully: ID={newest['id']}",
        "sale_order_id": order["id"],
        "invoice": newest,
    }


# ---------------------------------------------------------------- delivery date
@router.get("/delivery_date/query/{order_name}")
@router.get("/delivery_date/querry/{order_name}", include_in_schema=False)  # old spelling used by the flows
def get_delivery_date(order_name: str, odoo: Odoo):
    """Scheduled delivery date in local time: the committed date if set, otherwise the expected date."""
    order = _order_by_name(odoo, order_name, ["name", "commitment_date", "expected_date"])
    tz = odoo.settings.timezone
    scheduled = order["commitment_date"] or order["expected_date"]
    return {
        "order_name": order["name"],
        "scheduled_delivery_date": odoo_to_local(scheduled, tz),
        "commitment_date": odoo_to_local(order["commitment_date"], tz),
        "expected_date": odoo_to_local(order["expected_date"], tz),
    }


@router.put("/delivery_date/confirm/{order_name}/{decision}")
@router.put("/delivery_date/confirm/{order_name}/{decision}/{new_date}")
def decide_delivery_date(order_name: str, decision: str, odoo: Odoo, new_date: str | None = None):
    """Customer decision on the scheduled delivery date.
    - accept: keeps the date (new_date is ignored and may be omitted)
    - reject: new_date is required, e.g. '2025-10-20 15:30' (local time); it becomes the commitment date.
    Both decisions are logged as a note in the order's chatter."""
    decision = decision.lower()
    if decision not in ("accept", "reject"):
        raise HTTPException(422, "decision must be 'accept' or 'reject'")
    order = _order_by_name(odoo, order_name, ["state", "commitment_date", "expected_date"])
    if order["state"] == "cancel":
        raise HTTPException(409, f"Order {order_name} is cancelled")
    tz = odoo.settings.timezone

    if decision == "accept":
        current = odoo_to_local(order["commitment_date"] or order["expected_date"], tz)
        odoo.execute("sale.order", "message_post", [order["id"]],
                     body=f"Customer accepted the delivery date ({current}).",
                     message_type="comment", subtype_xmlid="mail.mt_note")
        return {"status": "accepted", "order_id": order["id"], "scheduled_delivery_date": current}

    if not new_date:
        raise HTTPException(422, "new_date is required when rejecting")
    try:
        proposed = parse_user_datetime(new_date, tz)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid new_date '{new_date}', expected e.g. 2025-10-20 15:30") from exc
    odoo.execute("sale.order", "write", [order["id"]], {"commitment_date": to_odoo(proposed)})
    local = odoo_to_local(to_odoo(proposed), tz)
    odoo.execute("sale.order", "message_post", [order["id"]],
                 body=f"Customer rejected the delivery date and proposed {local}.",
                 message_type="comment", subtype_xmlid="mail.mt_note")
    return {"status": "rejected_and_date_updated", "order_id": order["id"], "new_commitment_date": local}


# ---------------------------------------------------------------- documents
@router.get("/get/pdf/{order_id}")
def get_order_pdf(order_id: int, odoo: Odoo):
    """PDF of a quotation / sales order (report sale.report_saleorder)."""
    if not odoo.execute("sale.order", "search_count", [("id", "=", order_id)]):
        raise not_found(f"Order {order_id}")
    return pdf_response(odoo.fetch_report_pdf("sale.report_saleorder", order_id), f"sale_order_{order_id}.pdf")
