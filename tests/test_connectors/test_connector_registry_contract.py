"""The 连接器管理 screen was built on URLs the API never had.

``views/connectors/index.vue`` lists connectors from ``GET /connectors/status``
and syncs them with ``POST /connectors/{id}/sync``.  Neither route exists in
``src/connectors/router.py``, which has three routes: the Shopify webhook, the
Amazon order import, and the tracking handover.  So the screen opened on
"暂无连接器数据" — the fetch failed and the failure went to ``console.warn``,
which the operator never sees — and every 同步 button answered 404 with a
generic 同步失败.  Its 配置 buttons pushed ``/connectors/amazon-config`` while
the SPA route is ``/connectors/amazon-config/:connectorId``, so the router
matched nothing, and the two config screens behind them asked the operator to
type an **AWS access key** and a **Shopify Admin API token** into a web form and
post them to ``/connectors/amazon/config/{id}`` and ``/connectors/{id}/config``,
which also do not exist.  SP-API authenticates with an LWA client id/secret and
a refresh token, and Shopify's webhook is verified with the app's own
``SECRET_KEY`` — neither screen was collecting a credential this system can use,
and a form that collects secrets for no endpoint to consume is a liability, not
a feature.

The registry endpoints added here answer with what this build can do:

* ``GET /connectors/status`` — the connectors that exist, each with a
  ``capabilities`` map naming every action ``implemented`` / ``not_implemented``
  / ``not_available``, derived from the settings that are actually set.
* ``GET /connectors/{id}`` — one of them; an unknown id answers 404 naming the
  two that exist.
* ``POST /connectors/{id}/sync`` — 501 for Amazon (the outbound SP-API calls are
  unimplemented), 422 for Shopify (a push-only integration has nothing to pull),
  and both name the endpoints that do work.

Credential fields report **whether** a variable is set, never its value: a
secret that comes back over an authenticated GET is a secret in the browser's
memory, its history, and every log that records response bodies.
"""

import pytest

API = "/api/v1"


# FastAPI serialises a response model by attribute name, so the docstrings on
# ``CredentialField``/``ConnectorStatus`` are not keys in the response body;
# the test that greps the body for a secret has to use the real secret only.
_TEST_SECRET = "dev-secret-key-for-connector-registry-tests-0123456789"


@pytest.fixture(autouse=True)
async def _authenticated(async_client):
    """The registry reads live settings, so the test supplies a secret it can look for."""
    from src.config import settings
    from src.core.dependencies import get_current_user
    from src.main import app

    previous = settings.secret_key
    settings.secret_key = _TEST_SECRET
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "ctrreg_", "username": "ctrreg_", "roles": ["admin"],
    }
    yield
    settings.secret_key = previous
    app.dependency_overrides.pop(get_current_user, None)


def _fields(resp) -> str:
    body = resp.json()
    parts = [str((body.get("error") or {}).get("message") or ""), str(body.get("detail") or "")]
    parts += [f"{e.get('field')} {e.get('message')} {e.get('value')}" for e in body.get("errors") or []]
    return " | ".join(parts)


def _by_id(items, connector_id):
    return next(row for row in items if row["id"] == connector_id)


class TestStatusRegistry:
    async def test_the_screen_gets_the_connectors_that_exist(self, async_client):
        resp = await async_client.get(f"{API}/connectors/status")
        assert resp.status_code == 200
        items = resp.json()
        assert {row["id"] for row in items} == {"amazon", "shopify"}

    async def test_the_status_route_is_not_eaten_by_the_id_route(self, async_client):
        """``/status`` has to be declared before ``/{connector_id}``."""
        resp = await async_client.get(f"{API}/connectors/status")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_amazon_advertises_only_what_this_build_does(self, async_client):
        """"SP-API 集成" as a feature line promised four calls that are stubs."""
        resp = await async_client.get(f"{API}/connectors/status")
        amazon = _by_id(resp.json(), "amazon")
        assert amazon["capabilities"]["order_import"] == "implemented"
        assert amazon["capabilities"]["tracking_handover_record"] == "implemented"
        for action in ("tracking_upload", "order_status_poll", "inventory_sync"):
            assert amazon["capabilities"][action] == "not_implemented"

    async def test_shopify_says_it_is_push_only(self, async_client):
        resp = await async_client.get(f"{API}/connectors/status")
        shopify = _by_id(resp.json(), "shopify")
        assert shopify["capabilities"]["order_push"] == "implemented"
        assert shopify["capabilities"]["order_pull"] == "not_available"

    async def test_no_credential_value_ever_comes_back(self, async_client):
        """A secret returned by a GET is a secret in the browser and in its logs."""
        resp = await async_client.get(f"{API}/connectors/status")
        assert _TEST_SECRET not in resp.text
        for row in resp.json():
            for field in row["credentials"]:
                assert field["env"].startswith(("AMAZON_SP_API_", "SECRET_KEY"))
                if field["env"] != "AMAZON_SP_API_REGION":
                    # Region is a marketplace selector, not a secret; every other
                    # field is a credential, and credentials publish only the
                    # env var's name and whether it is set.
                    assert field.get("value") is None, field

    async def test_the_region_is_shown_because_it_is_a_selector_not_a_secret(self, async_client):
        resp = await async_client.get(f"{API}/connectors/status")
        amazon = _by_id(resp.json(), "amazon")
        from src.config import settings

        region = next(f for f in amazon["credentials"] if f["env"] == "AMAZON_SP_API_REGION")
        assert region["value"] == settings.amazon_sp_api_region

    async def test_a_credential_that_is_set_is_reported_as_set_without_its_value(self, async_client):
        resp = await async_client.get(f"{API}/connectors/status")
        shopify = _by_id(resp.json(), "shopify")
        assert shopify["configured"] is True
        assert shopify["status"] == "active"
        field = shopify["credentials"][0]
        assert field["env"] == "SECRET_KEY"
        assert field["set"] is True
        assert field.get("value") is None

    async def test_the_registry_names_the_credentials_the_settings_read(self, async_client):
        resp = await async_client.get(f"{API}/connectors/status")
        amazon = _by_id(resp.json(), "amazon")
        assert [f["env"] for f in amazon["credentials"]] == [
            "AMAZON_SP_API_CLIENT_ID",
            "AMAZON_SP_API_CLIENT_SECRET",
            "AMAZON_SP_API_REFRESH_TOKEN",
            "AMAZON_SP_API_REGION",
        ]
        # Every field is reported as unset in a test run, which is the truth for
        # this deployment: the point is that the answer tracks the settings.
        assert all(f["set"] is False for f in amazon["credentials"][:3])
        assert amazon["configured"] is False
        assert amazon["status"] == "not_configured"


class TestConnectorDetail:
    async def test_one_connector_by_id(self, async_client):
        resp = await async_client.get(f"{API}/connectors/amazon")
        assert resp.status_code == 200
        assert resp.json()["id"] == "amazon"

    async def test_a_connector_that_was_never_built_answers_404(self, async_client):
        """"SAP PI/PO + Oracle EDI 对接" was advertised in the README; no such connector exists."""
        for missing in ("sap", "oracle", "erp"):
            resp = await async_client.get(f"{API}/connectors/{missing}")
            assert resp.status_code == 404, resp.text
            assert "amazon and shopify" in _fields(resp)

    async def test_the_id_is_case_insensitive(self, async_client):
        resp = await async_client.get(f"{API}/connectors/Shopify")
        assert resp.status_code == 200
        assert resp.json()["id"] == "shopify"


class TestSyncAction:
    async def test_amazon_sync_says_the_outbound_calls_are_not_built(self, async_client):
        """A 同步 button answering 200 is a sync the operator believes happened."""
        resp = await async_client.post(f"{API}/connectors/amazon/sync")
        assert resp.status_code == 501
        fields = _fields(resp)
        assert "未实现" in fields
        # The answer also says what to use instead, which is the screen's job.
        assert "/connectors/amazon/orders" in fields

    async def test_shopify_sync_says_there_is_nothing_to_pull(self, async_client):
        resp = await async_client.post(f"{API}/connectors/shopify/sync")
        assert resp.status_code == 422
        assert "推送" in _fields(resp)

    async def test_an_unknown_connector_says_which_ones_exist(self, async_client):
        resp = await async_client.post(f"{API}/connectors/oracle/sync")
        assert resp.status_code == 404
        assert "amazon and shopify" in _fields(resp)

    async def test_the_error_codes_are_the_envelope_codes(self, async_client):
        resp = await async_client.post(f"{API}/connectors/amazon/sync")
        assert resp.json()["error"]["code"] == "NOT_IMPLEMENTED"
        resp = await async_client.post(f"{API}/connectors/shopify/sync")
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        resp = await async_client.post(f"{API}/connectors/sap/sync")
        assert resp.json()["error"]["code"] == "NOT_FOUND"
