"""The mobile client's request paths against the routes that actually exist.

Two of the defects fixed in this repo were path mistakes on the phone side: the
PDA posted a purchase-order receipt to ``/purchase-orders/{id}/receive`` when
the route lives under ``/warehouses``, and it probed ``GET /pda/sync`` for
liveness when sync is POST-only.  Both looked like network failures on the
device — and a 404 filed by the offline queue is worse than a crash, because
the queue records a scan as permanently rejected and drops it.

The API is mounted in two places, and getting that wrong is the same class of
bug: ``src/main.py`` mounts the REST routers under ``/api/v1`` and the PDA
router at the root, so ``/api/v1/pda/mutations`` 404s while ``/pda/mutations``
answers.  This test therefore resolves each call against the mount its helper
implies — ``request()`` against /api/v1, ``pdaRequest()`` against /pda — and
checks the path against the routes FastAPI actually registered there.

This is a cheap contract check rather than a full schema check: it does not
know what a response looks like, but it does know that every path the app can
build reaches some route.
"""

import pathlib
import re

import pytest

from src.main import app

MOBILE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "mobile"
CLIENT_FILE = MOBILE_ROOT / "src" / "api" / "client.js"
APP_FILE = MOBILE_ROOT / "App.js"
API_PREFIX = "/api/v1"
PDA_PREFIX = "/pda"

_METHODS = "GET|POST|PATCH|PUT|DELETE"

# request("POST", `/warehouses/${encodeURIComponent(id)}/locations`)
_REQUEST_RE = re.compile(
    rf"""(?<![A-Za-z])request\(\s*"({_METHODS})"\s*,\s*(?:"([^"]*)"|`([^`]*)`)""",
    re.MULTILINE,
)
# pdaRequest("GET", "/mutations?limit=1") — the same call aimed at the root mount.
_PDA_REQUEST_RE = re.compile(
    rf"""pdaRequest\(\s*"({_METHODS})"\s*,\s*(?:"([^"]*)"|`([^`]*)`)""",
    re.MULTILINE,
)


def _parse(source: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    calls = []
    for method, quoted, template in pattern.findall(source):
        calls.append((method, quoted if quoted else template))
    return calls


def _client_calls() -> list[tuple[str, str, str]]:
    """Every request the client can build, as (mount prefix, method, path)."""
    source = CLIENT_FILE.read_text(encoding="utf-8")
    return (
        [(API_PREFIX, m, p) for m, p in _parse(source, _REQUEST_RE)]
        + [(PDA_PREFIX, m, p) for m, p in _parse(source, _PDA_REQUEST_RE)]
    )


def _segments(path: str) -> list[str]:
    """Path → segments, with `${...}` and `{param}` both collapsed to '*'."""
    path = path.split("?", 1)[0]
    return [
        "*" if segment.startswith("${") or segment.startswith("{") else segment
        for segment in path.strip("/").split("/")
        if segment
    ]


def _server_routes(prefix: str) -> list[tuple[str, list[str]]]:
    routes = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        if not path.startswith(prefix):
            continue
        segments = _segments(path[len(prefix):] or "/")
        for method in methods - {"HEAD", "OPTIONS"}:
            routes.append((method, segments))
    return routes


def _matches(client: list[str], server: list[str]) -> bool:
    if len(client) != len(server):
        return False
    return all(c == "*" or s == "*" or c == s for c, s in zip(client, server))


def test_client_file_is_present():
    assert CLIENT_FILE.exists(), f"missing {CLIENT_FILE}"


def test_both_mounts_are_served():
    """A client check against a mount that was never wired up passes vacuously."""
    for prefix in (API_PREFIX, PDA_PREFIX):
        assert _server_routes(prefix), f"no {prefix} routes found — is src.main.app wired up?"


def test_every_client_path_reaches_a_route():
    unmatched = []
    for prefix, method, path in _client_calls():
        segments = _segments(path)
        if not any(
            method == route_method and _matches(segments, route_segments)
            for route_method, route_segments in _server_routes(prefix)
        ):
            unmatched.append(f"{method} {prefix}{path}")

    # One message listing every offender: these are the paths a PDA will fail
    # on, and fixing one at a time is how the next one ships.
    assert not unmatched, "mobile client calls paths the API does not serve: " + ", ".join(sorted(unmatched))


@pytest.mark.parametrize("prefix,method,path", _client_calls())
def test_path_is_absolute_and_unquoted(prefix: str, method: str, path: str):
    """A relative or doubled-up path resolves against the base URL into a 404."""
    assert path.startswith("/"), f"{method} {path!r} is not absolute"
    assert "//" not in path.replace("://", ""), f"{method} {path!r} contains a doubled slash"
    assert "${BASE_URL}" not in path, f"{method} {path!r} repeats the base URL"


def test_no_socket_address_is_hardcoded_in_the_client():
    """
    A literal ``ws://…`` in the client is a host that only exists on one machine.

    The socket used to default to ``ws://10.0.2.2:8000/pda/ws?client_id=`` — the
    Android emulator's alias for the developer's laptop — so a real handheld in
    the warehouse dialled a private address, never connected, and the offline
    queue lost the one event that would have replayed it early.  The URL has to
    come from the same API root the REST calls use.
    """
    source = CLIENT_FILE.read_text(encoding="utf-8")
    for literal in ('"ws://', "'ws://", '"wss://', "'wss://"):
        assert literal not in source, f"client.js hardcodes a socket address ({literal})"
    assert 'replace(/^http/, "ws")' in source, "the socket URL is not derived from API_ROOT"


def test_the_realtime_channel_is_actually_started():
    """
    A socket manager nothing connects is the same as no channel at all.

    ``pdaSocket`` was exported and never called, so the trigger that replays a
    loaded queue the moment a PDA regains signal never fired — the queue waited
    out its slow heartbeat tick instead, and the operator re-scanned.
    """
    source = APP_FILE.read_text(encoding="utf-8")
    assert "pdaSocket.connect" in source, "App.js never connects the PDA socket"
    assert "startOfflineAutoSync" in source, "App.js never starts the queue's own pump"


def test_pda_paths_use_the_pda_helper():
    """
    A /pda path sent through request() goes out under /api/v1 and 404s.

    The queue is the reason that is not just ugly: pdaRequest() refuses to queue
    because replays are stored API_BASE-relative, so an inlined request() call
    would file the mutation as permanently rejected and throw the scan away.
    """
    source = CLIENT_FILE.read_text(encoding="utf-8")
    offenders = [f"{method} {path}" for method, path in _parse(source, _REQUEST_RE) if path.startswith("/pda")]
    assert not offenders, "PDA paths must go through pdaRequest(): " + ", ".join(sorted(offenders))
