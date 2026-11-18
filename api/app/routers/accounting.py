from fastapi import APIRouter, HTTPException

from ..dependencies import Odoo, find_one, not_found, pdf_response
from ..odoo import OdooClient

router = APIRouter(prefix="/accounting", tags=["Accounting"])

INVOICE_FIELDS = ["id", "name", "invoice_date", "amount_total", "state", "payment_state"]


@router.get("/invoice/by_saleorder/{order_name}")
def get_invoices_of_order(order_name: str, odoo: Odoo):
    """All invoices of a sales order, newest first. `invoice` is an empty list when there is none."""
    order = find_one(odoo, "sale.order", [("name", "=", order_name)], ["invoice_ids"], f"Order {order_name}")
    invoices = []
    if order["invoice_ids"]:
        invoices = odoo.execute("account.move", "read", order["invoice_ids"], fields=INVOICE_FIELDS)
        invoices.sort(key=lambda inv: inv["id"], reverse=True)
    return {"sale_order_id": order["id"], "invoice": invoices}


@router.get("/invoice/get/pdf/{invoice_id}")
def get_invoice_pdf(invoice_id: int, odoo: Odoo):
    """PDF of a customer invoice (report account.report_invoice_with_payments)."""
    if not odoo.execute("account.move", "search_count", [("id", "=", invoice_id)]):
        raise not_found(f"Invoice {invoice_id}")
    content = odoo.fetch_report_pdf("account.report_invoice_with_payments", invoice_id)
    return pdf_response(content, f"invoice_{invoice_id}.pdf")


def _invoice(odoo: OdooClient, invoice_id: int) -> dict:
    return find_one(odoo, "account.move", [("id", "=", invoice_id)], INVOICE_FIELDS, f"Invoice {invoice_id}")


@router.post("/invoice/{invoice_id}/confirm")
def confirm_invoice(invoice_id: int, odoo: Odoo):
    """Post a draft invoice (button 'Confirm', account.move.action_post): it gets its number."""
    invoice = _invoice(odoo, invoice_id)
    if invoice["state"] != "draft":
        raise HTTPException(409, f"Invoice {invoice['name'] or invoice_id} is '{invoice['state']}', not a draft")
    odoo.execute("account.move", "action_post", [invoice_id])
    invoice = _invoice(odoo, invoice_id)
    if invoice["state"] != "posted":
        raise HTTPException(409, f"Odoo did not post invoice {invoice_id}")
    return {"message": f"Invoice {invoice['name']} confirmed", "invoice": invoice}


@router.post("/invoice/{invoice_id}/pay")
def register_payment(invoice_id: int, odoo: Odoo):
    """Register the full payment of a posted invoice (button 'Pay', wizard account.payment.register)."""
    invoice = _invoice(odoo, invoice_id)
    if invoice["state"] != "posted":
        raise HTTPException(409, f"Invoice {invoice['name'] or invoice_id} must be confirmed before payment")
    if invoice["payment_state"] in ("paid", "in_payment", "reversed"):
        raise HTTPException(409, f"Invoice {invoice['name']} is already paid")
    context = {"active_model": "account.move", "active_ids": [invoice_id]}
    wizard = odoo.execute("account.payment.register", "create", {}, context=context)
    odoo.execute("account.payment.register", "action_create_payments", [wizard], context=context)
    invoice = _invoice(odoo, invoice_id)
    if invoice["payment_state"] not in ("paid", "in_payment"):
        raise HTTPException(409, f"Odoo did not register the payment of {invoice['name']}")
    return {"message": f"Payment of {invoice['name']} registered", "invoice": invoice}
