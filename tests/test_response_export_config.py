from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse

from src.core.response import (
    ApiResponse,
    bad_gateway_response,
    bad_request_response,
    conflict_response,
    create_response,
    delete_response,
    detail_response,
    error_response,
    forbidden_response,
    health_check_response,
    internal_error_response,
    list_response,
    method_not_allowed_response,
    not_found_response,
    not_implemented_response,
    paginated_response,
    rate_limit_exceeded_response,
    readiness_check_response,
    server_error_response,
    service_unavailable_response,
    success_response,
    unauthorized_response,
    unknown_error_response,
    update_response,
    validate_error_response,
)


class TestApiResponse:
    def test_defaults(self):
        r = ApiResponse()
        assert r.success is True
        assert r.data is None
        assert r.message is None
        assert r.meta is None

    def test_full(self):
        r = ApiResponse(data={"id": 1}, message="OK", meta={"page": 1})
        assert r.to_dict() == {"success": True, "data": {"id": 1}, "message": "OK", "meta": {"page": 1}}

    def test_to_dict_no_optionals(self):
        r = ApiResponse(data=[1, 2])
        assert r.to_dict() == {"success": True, "data": [1, 2]}

    def test_to_response(self):
        r = ApiResponse(data="ok")
        resp = r.to_response()
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 200


class TestSuccessResponse:
    def test_basic(self):
        r = success_response(data="done")
        assert r.data == "done"
        assert r.message is None

    def test_with_message(self):
        r = success_response(data=[], message="All good")
        assert r.message == "All good"

    def test_with_meta(self):
        r = success_response(data=[], meta={"total": 0})
        assert r.meta == {"total": 0}


class TestErrorResponse:
    def test_basic(self):
        resp = error_response()
        data = resp.body.decode()
        assert resp.status_code == 400
        assert "false" in data
        assert '"ERROR"' in data

    def test_with_errors(self):
        resp = error_response(status_code=422, code="VALIDATION", message="Bad input", errors=[{"field": "name"}])
        assert resp.status_code == 422
        body = resp.body.decode()
        assert "VALIDATION" in body
        assert "Bad input" in body
        assert "name" in body


class TestPaginatedResponse:
    def test_basic(self):
        r = paginated_response(data=[1, 2, 3], total_count=50, page=2, per_page=10)
        assert r.data == [1, 2, 3]
        meta = r.meta["pagination"]
        assert meta["page"] == 2
        assert meta["per_page"] == 10
        assert meta["total_count"] == 50
        assert meta["total_pages"] == 5
        assert meta["has_next"] is True
        assert meta["has_prev"] is True

    def test_first_page_no_prev(self):
        r = paginated_response(data=[], total_count=100, page=1, per_page=20)
        meta = r.meta["pagination"]
        assert meta["has_prev"] is False
        assert meta["has_next"] is True

    def test_last_page_no_next(self):
        r = paginated_response(data=[], total_count=15, page=2, per_page=10)
        meta = r.meta["pagination"]
        assert meta["has_next"] is False
        assert meta["has_prev"] is True


class TestConvenienceResponses:
    def test_list_response(self):
        r = list_response(data=[1, 2, 3], message="Listed")
        assert r.data == [1, 2, 3]
        assert r.message == "Listed"

    def test_detail_response(self):
        r = detail_response(data={"id": 1}, message="Detail")
        assert r.data == {"id": 1}

    def test_delete_response(self):
        r = delete_response()
        assert r.data is None
        assert r.message == "Resource deleted successfully"

    def test_create_response(self):
        r = create_response(data={"id": 1})
        assert r.data == {"id": 1}

    def test_update_response(self):
        r = update_response(data={"id": 1})
        assert r.data == {"id": 1}

    def test_validate_error_response(self):
        resp = validate_error_response(errors=[{"field": "email"}])
        assert resp.status_code == 422
        assert "VALIDATION_ERROR" in resp.body.decode()

    def test_not_found_response(self):
        resp = not_found_response()
        assert resp.status_code == 404

    def test_not_found_response_custom(self):
        resp = not_found_response("Order missing")
        assert "Order missing" in resp.body.decode()

    def test_unauthorized_response(self):
        resp = unauthorized_response()
        assert resp.status_code == 401

    def test_forbidden_response(self):
        resp = forbidden_response()
        assert resp.status_code == 403

    def test_forbidden_response_custom(self):
        resp = forbidden_response("No access")
        assert "No access" in resp.body.decode()

    def test_rate_limit_exceeded_response(self):
        resp = rate_limit_exceeded_response()
        assert resp.status_code == 429

    def test_server_error_response(self):
        resp = server_error_response()
        assert resp.status_code == 500

    def test_bad_request_response(self):
        resp = bad_request_response()
        assert resp.status_code == 400

    def test_method_not_allowed_response(self):
        resp = method_not_allowed_response()
        assert resp.status_code == 405

    def test_not_implemented_response(self):
        resp = not_implemented_response()
        assert resp.status_code == 501

    def test_conflict_response(self):
        resp = conflict_response()
        assert resp.status_code == 409

    def test_bad_gateway_response(self):
        resp = bad_gateway_response()
        assert resp.status_code == 502

    def test_service_unavailable_response(self):
        resp = service_unavailable_response()
        assert resp.status_code == 503

    def test_internal_error_response(self):
        resp = internal_error_response()
        assert resp.status_code == 500

    def test_unknown_error_response(self):
        resp = unknown_error_response()
        assert resp.status_code == 500

    def test_health_check_response(self):
        r = health_check_response()
        assert r.data["status"] == "ok"
        assert r.message == "Service is healthy"

    def test_readiness_check_response(self):
        r = readiness_check_response()
        assert r.data["status"] == "ready"
        assert r.message == "Service is ready to accept requests"


class TestExport:
    @pytest.mark.skip(reason="import chain triggers bcrypt")
    def placeholder(self):
        pass
