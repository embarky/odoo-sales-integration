from fastapi import APIRouter

from ..dependencies import Odoo, find_one, not_found, pdf_response

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
