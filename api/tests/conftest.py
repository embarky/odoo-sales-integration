import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_odoo
from app.main import app
from app.odoo import OdooClient

from .fake_odoo import DB, LOGIN, PASSWORD, start_server


@pytest.fixture
def odoo_server():
    server, fake, url = start_server()
    yield fake, url
    server.shutdown()
    server.server_close()


@pytest.fixture
def odoo_client(odoo_server):
    _, url = odoo_server
    return OdooClient(Settings(odoo_url=url, odoo_db=DB, odoo_user=LOGIN, odoo_password=PASSWORD, odoo_timeout=5))


@pytest.fixture
def fake(odoo_server):
    return odoo_server[0]


@pytest.fixture
def client(odoo_client):
    app.dependency_overrides[get_odoo] = lambda: odoo_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
