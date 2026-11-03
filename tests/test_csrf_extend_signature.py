"""The extend-signature HMAC is bound to a client address — a header must not pick it.

Signature = HMAC-SHA256(secret, "path:timestamp:client_ip").  The only reason to
fold the client address into the signature is to make a captured
(path, timestamp, signature) triple unusable from another machine.  When the
server derives ``client_ip`` from ``X-Real-Ip`` / ``X-Forwarded-For``, the attacker
who replayed the triple simply sets that header to the original client's address
and the binding is void (M6 in 补充开发修复计划.md — the code read the header
*first*, ahead of the TCP peer).

Headers may decide the address only when the peer itself is a proxy we are
configured to trust: ``settings.trusted_proxy_ips``.
"""

import hashlib
import hmac
import time

from starlette.requests import Request

from src.config import settings
from src.core import csrf as csrf_module

PATH = "/api/v1/extend/pda/sync"


def _request(*, peer: tuple[str, int], headers: dict[str, str] | None = None, path: str = PATH) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": peer,
        "server": ("testserver", 80),
    }
    return Request(scope)


def _sign(path: str, timestamp: int, client_ip: str) -> str:
    message = f"{path}:{timestamp}:{client_ip}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def _headers(timestamp: int, signature: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"X-Extend-Timestamp": str(timestamp), "X-Extend-Signature": signature, **(extra or {})}


def test_a_header_cannot_choose_the_address_the_signature_is_bound_to():
    """Peer address wins; X-Real-Ip is attacker-settable and must not be consulted."""
    original_victim = "203.0.113.9"
    actual_peer = "198.51.100.7"

    request = _request(
        peer=(actual_peer, 50000),
        headers={"X-Real-Ip": original_victim, "X-Forwarded-For": original_victim},
    )

    assert csrf_module._client_ip_for_signature(request) == actual_peer


def test_signature_minted_for_one_client_is_rejected_when_replayed_from_another():
    """The whole point of binding the address: replay from a different machine fails."""
    victim_ip = "203.0.113.9"
    timestamp = int(time.time())
    stolen = _sign(PATH, timestamp, victim_ip)

    replay = _request(
        peer=("198.51.100.7", 50000),
        headers=_headers(timestamp, stolen, {"X-Real-Ip": victim_ip}),
    )

    assert csrf_module._verify_extend_signature(replay) is False


def test_signature_from_the_address_the_peer_really_has_is_accepted():
    peer_ip = "198.51.100.7"
    timestamp = int(time.time())

    request = _request(peer=(peer_ip, 50000), headers=_headers(timestamp, _sign(PATH, timestamp, peer_ip)))

    assert csrf_module._verify_extend_signature(request) is True


def test_a_trusted_proxy_may_forward_the_real_client(monkeypatch):
    """Behind a proxy the peer is the proxy, so a forwarding header is legitimate there."""
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.1, 10.0.0.2")
    real_client = "203.0.113.7"
    timestamp = int(time.time())

    forwarded = f"{real_client}, 10.0.0.1"
    request = _request(
        peer=("10.0.0.1", 50000),
        headers=_headers(timestamp, _sign(PATH, timestamp, real_client), {"X-Forwarded-For": forwarded}),
    )

    assert csrf_module._verify_extend_signature(request) is True


def test_untrusted_peer_forwarding_the_client_address_is_still_rejected(monkeypatch):
    """The proxy allowance must not become a general "trust the header" switch."""
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.1")
    claimed_client = "203.0.113.7"
    timestamp = int(time.time())

    request = _request(
        peer=("198.51.100.7", 50000),
        headers=_headers(timestamp, _sign(PATH, timestamp, claimed_client), {"X-Forwarded-For": claimed_client}),
    )

    assert csrf_module._verify_extend_signature(request) is False


async def test_middleware_answers_403_for_the_replay(async_client):
    """End to end: CsrfMiddleware gates the request on this, not just the helper.

    No /api/v1/extend route is mounted today, so a *verified* request would fall
    through to 404 — 403 here means the signature was rejected before dispatch.
    """
    timestamp = int(time.time())

    response = await async_client.post(
        PATH,
        json={},
        headers=_headers(timestamp, _sign(PATH, timestamp, "203.0.113.9"), {"X-Real-Ip": "203.0.113.9"}),
    )

    assert response.status_code == 403, f"expected 403, got {response.status_code}"
