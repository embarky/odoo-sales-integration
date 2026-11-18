from fastapi import APIRouter

from ..dependencies import Odoo

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("/all")
def get_all_vendors(odoo: Odoo):
    """All partners that are vendors (supplier_rank > 0), as {value, label} pairs."""
    rows = odoo.execute("res.partner", "search_read", [("supplier_rank", ">", 0)], fields=["name"], order="name")
    return [{"value": r["id"], "label": r["name"]} for r in rows]
