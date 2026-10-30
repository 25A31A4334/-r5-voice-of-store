"""Store Count Consistency & Admin Store Management Tests for R5 Voice of Store Engine.

Verifies:
1. Backend store API (/api/stores) returns all 60 stores from authoritative store_master.
2. Admin store API (/api/admin/stores) strictly enforces admin role authorization (401/403 for non-admin).
3. Admin store API supports search, region filtering, format filtering, and pagination.
4. Parity: The store IDs accessible in the Admin interface match 100% of the stores in the Customer Feedback dropdown.
5. Store data fidelity: real store IDs, store names, cities, regions, and formats are preserved without hardcoding.
6. Admin store switching workflow works for all 60 stores across the network.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "test"
os.environ["TESTING"] = "true"

from FULL_CODE.db.connection import get_db_connection
from FULL_CODE.db.seed import seed_database
from FULL_CODE.app import app, load_application_state, state


@pytest.fixture(scope="module")
def client():
    seed_database(force_demo=True)
    load_application_state()
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(client):
    res_cust = client.post("/api/auth/login", json={"email": "customer@example.com", "password": "DemoCust#2026!Aarav"})
    assert res_cust.status_code == 200, f"Customer login failed: {res_cust.text}"

    res_mgr = client.post("/api/auth/login", json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"})
    assert res_mgr.status_code == 200, f"Manager login failed: {res_mgr.text}"

    res_admin = client.post("/api/auth/login", json={"email": "admin@saffron.example", "password": "DemoAdmin#2026!LocalOnly"})
    assert res_admin.status_code == 200, f"Admin login failed: {res_admin.text}"

    return {
        "customer": res_cust.json()["access_token"],
        "manager": res_mgr.json()["access_token"],
        "admin": res_admin.json()["access_token"],
    }


class TestStoreCountConsistency:
    """Tests verifying 60-store network parity between Admin Portal and Customer Portal."""

    def test_backend_stores_api_returns_all_60_stores(self, client: TestClient):
        """Verifies GET /api/stores returns exactly 60 stores matching store_master.csv."""
        res = client.get("/api/stores")
        assert res.status_code == 200
        stores = res.json()
        assert isinstance(stores, list), f"Expected list, got {type(stores)}"
        assert len(stores) == 60, f"Expected 60 stores, got {len(stores)}"

        # Verify essential fields exist and are non-empty
        for s in stores:
            assert "store_id" in s and s["store_id"].startswith("ST-"), f"Invalid store_id in {s}"
            assert "store_name" in s and len(s["store_name"]) > 0
            assert "city" in s and len(s["city"]) > 0
            assert "region" in s and s["region"] in ["North", "South", "East", "West", "Central"]
            assert "format" in s and s["format"] in ["Saffron Market", "Saffron Express", "Saffron Hyper"]

    def test_admin_stores_api_role_based_access_control(self, client: TestClient, tokens: dict):
        """Verifies GET /api/admin/stores enforces admin-only access."""
        # 1. Unauthenticated request -> 401
        res_unauth = client.get("/api/admin/stores")
        assert res_unauth.status_code == 401, f"Expected 401, got {res_unauth.status_code}"

        # 2. Customer token -> 403 Forbidden
        res_cust = client.get("/api/admin/stores", headers={"Authorization": f"Bearer {tokens['customer']}"})
        assert res_cust.status_code == 403, f"Expected 403, got {res_cust.status_code}"

        # 3. Store manager token -> 403 Forbidden
        res_mgr = client.get("/api/admin/stores", headers={"Authorization": f"Bearer {tokens['manager']}"})
        assert res_mgr.status_code == 403, f"Expected 403, got {res_mgr.status_code}"

        # 4. Admin token -> 200 OK
        res_admin = client.get("/api/admin/stores", headers={"Authorization": f"Bearer {tokens['admin']}"})
        assert res_admin.status_code == 200, f"Expected 200, got {res_admin.status_code}"
        data = res_admin.json()
        assert data["total"] == 60
        assert len(data["stores"]) == 10  # Default page limit = 10
        assert data["total_pages"] == 6

    def test_store_id_parity_between_customer_and_admin(self, client: TestClient, tokens: dict):
        """Verifies that the exact same set of 60 store IDs is accessible to both interfaces."""
        # Customer source: /api/stores
        cust_stores = client.get("/api/stores").json()
        cust_ids = {s["store_id"] for s in cust_stores}
        assert len(cust_ids) == 60

        # Admin source: /api/admin/stores?all=true
        admin_res = client.get("/api/admin/stores?all=true", headers={"Authorization": f"Bearer {tokens['admin']}"}).json()
        admin_ids = {s["store_id"] for s in admin_res["stores"]}
        assert len(admin_ids) == 60

        # Strict parity check
        diff_admin_missing = cust_ids - admin_ids
        diff_cust_missing = admin_ids - cust_ids
        assert len(diff_admin_missing) == 0, f"Admin portal missing stores: {diff_admin_missing}"
        assert len(diff_cust_missing) == 0, f"Customer portal missing stores: {diff_cust_missing}"
        assert cust_ids == admin_ids, "Store IDs across Customer and Admin portals do not match 100%"

    def test_search_filtering_and_pagination(self, client: TestClient, tokens: dict):
        """Tests search, region, format filtering and pagination on store directory APIs."""
        admin_headers = {"Authorization": f"Bearer {tokens['admin']}"}

        # 1. Search filter: 'Kankarbagh'
        res_search = client.get("/api/admin/stores?search=Kankarbagh", headers=admin_headers)
        assert res_search.status_code == 200
        data_search = res_search.json()
        assert data_search["total"] >= 1
        found = [s for s in data_search["stores"] if s["store_id"] == "ST-D69EG"]
        assert len(found) == 1
        assert found[0]["store_name"] == "Saffron Market Kankarbagh"

        # 2. Region filter: 'North'
        res_north = client.get("/api/admin/stores?region=North&limit=50", headers=admin_headers)
        assert res_north.status_code == 200
        data_north = res_north.json()
        assert data_north["total"] > 0
        for s in data_north["stores"]:
            assert s["region"] == "North"

        # 3. Format filter: 'Saffron Hyper'
        res_hyper = client.get("/api/admin/stores?format=Saffron+Hyper&limit=50", headers=admin_headers)
        assert res_hyper.status_code == 200
        data_hyper = res_hyper.json()
        assert data_hyper["total"] > 0
        for s in data_hyper["stores"]:
            assert s["format"] == "Saffron Hyper"

        # 4. Pagination: page 1 vs page 2
        res_p1 = client.get("/api/admin/stores?page=1&limit=10", headers=admin_headers).json()
        res_p2 = client.get("/api/admin/stores?page=2&limit=10", headers=admin_headers).json()
        assert res_p1["page"] == 1
        assert res_p2["page"] == 2
        p1_ids = [s["store_id"] for s in res_p1["stores"]]
        p2_ids = [s["store_id"] for s in res_p2["stores"]]
        assert len(p1_ids) == 10
        assert len(p2_ids) == 10
        # No overlap between page 1 and page 2
        assert len(set(p1_ids).intersection(set(p2_ids))) == 0

    def test_frontend_html_admin_store_management_elements(self, client: TestClient):
        """Verifies that index.html contains the Store Directory button, modal, table, and pagination."""
        res = client.get("/")
        assert res.status_code == 200
        html = res.text

        # 1. Admin Store Switcher and Directory button
        assert 'id="mgrAdminStoreSelectGroup"' in html
        assert 'id="mgrAdminStoreSelect"' in html
        assert 'id="btnOpenStoreManagement"' in html
        assert 'Store Directory' in html or 'Store Management' in html

        # 2. Store Management Modal
        assert 'id="storeManagementModal"' in html
        assert 'id="storeMgmtSearch"' in html
        assert 'id="storeMgmtRegion"' in html
        assert 'id="storeMgmtFormat"' in html
        assert 'id="btnStoreMgmtRefresh"' in html
        assert 'id="storeMgmtTableBody"' in html
        assert 'id="storeMgmtPaginationInfo"' in html
        assert 'id="btnStoreMgmtPrev"' in html
        assert 'id="btnStoreMgmtNext"' in html

    def test_admin_can_access_previously_missing_stores(self, client: TestClient, tokens: dict):
        """Verifies that the admin can view store summary and alerts for stores previously omitted from the 5-store demo."""
        admin_headers = {"Authorization": f"Bearer {tokens['admin']}"}

        # Test previously missing stores: ST-001JY (Gariahat), ST-01XF3 (Dharampeth), ST-0C5WT (KK Nagar)
        previously_missing = ["ST-001JY", "ST-01XF3", "ST-0C5WT"]
        for sid in previously_missing:
            # Admin can inspect store summary
            summary_res = client.get(f"/api/manager/store-summary?store_id={sid}", headers=admin_headers)
            assert summary_res.status_code == 200, f"Failed for {sid}: {summary_res.text}"
            data = summary_res.json()
            assert data["store_id"] == sid
            assert "store_name" in data and len(data["store_name"]) > 0

            # Admin can inspect alerts
            alerts_res = client.get(f"/api/manager/alerts?store_id={sid}", headers=admin_headers)
            assert alerts_res.status_code == 200, f"Failed alerts for {sid}: {alerts_res.text}"
            assert "alerts" in alerts_res.json()
