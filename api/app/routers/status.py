from fastapi import APIRouter

from ..dependencies import Odoo

router = APIRouter(tags=["Status"])


@router.get("/get-status")
def get_status(odoo: Odoo):
    """Check that Odoo is reachable and that the API credentials are valid."""
    version = odoo.version()
    uid = odoo.uid
    s = odoo.settings
    return {
        "Message": f"user {uid} connected: Odoo version {version.get('server_version')} "
                   f"is waiting for requests on {s.odoo_db}.",
        "server_version": version.get("server_version"),
        "uid": uid,
    }
