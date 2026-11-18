from fastapi import APIRouter

from ..dependencies import Odoo, not_found

router = APIRouter(prefix="/customers", tags=["Customers"])


def _as_options(rows: list[dict]) -> list[dict]:
    # {value, label} is the format used by the Node-RED list/table widgets
    return [{"value": r["id"], "label": r["name"]} for r in rows]


# /all and /companies must be declared before /{cust_id}
@router.get("/all")
def get_all_customers(odoo: Odoo):
    """All partners that are customers (customer_rank > 0)."""
    rows = odoo.execute("res.partner", "search_read", [("customer_rank", ">", 0)], fields=["name"], order="name")
    return _as_options(rows)


@router.get("/companies")
def get_company_customers(odoo: Odoo):
    """Business customers only (is_company = True)."""
    rows = odoo.execute(
        "res.partner", "search_read",
        [("is_company", "=", True), ("customer_rank", ">", 0)], fields=["name"], order="name",
    )
    return _as_options(rows)


@router.get("/{cust_id}")
def get_customer(cust_id: int, odoo: Odoo):
    """Details of one customer. Returned as a one-element list (format used by the dashboard)."""
    rows = odoo.execute(
        "res.partner", "search_read", [("id", "=", cust_id)],
        fields=["name", "email", "phone", "street", "city", "zip", "country_id", "comment", "is_company"],
    )
    if not rows:
        raise not_found(f"Customer {cust_id}")
    return rows
