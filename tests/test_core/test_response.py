"""Tests for unified API response helpers — pure functions, no async needed."""
import math

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
    def test_init_defaults(self):
        r = ApiResponse()
        assert r.success is True
        assert r.data is None
        assert r.message is None
        assert r.meta is None

    def test_init_with_data(self):
        r = ApiResponse(data={"id": 1})
        assert r.data == {"id": 1}

    def test_to_dict_no_optional(self):
        r = ApiResponse(data="ok")
        d = r.to_dict()
        assert d == {"success": True, "data": "ok"}

    def test_to_dict_with_message(self):
        r = ApiResponse(data="ok", message="done")
        d = r.to_dict()
        assert d["message"] == "done"

    def test_to_dict_with_meta(self):
        r = ApiResponse(data=[], meta={"page": 1})
        d = r.to_dict()
        assert d["meta"] == {"page": 1}

    def test_to_response(self):
        r = ApiResponse(data="ok")
        resp = r.to_response()
        assert resp.status_code == 200
        body = resp.body.decode()
        assert '"success":true' in body
        assert '"data":"ok"' in body


class TestSuccessResponse:
    def test_minimal(self):
        r = success_response()
        assert r.data is None
        assert r.message is None
        assert r.meta is None

    def test_full(self):
        r = success_response(data=[1, 2], message="loaded", meta={"count": 2})
        assert r.data == [1, 2]
        assert r.message == "loaded"
        assert r.meta == {"count": 2}


class TestErrorResponse:
    def test_minimal(self):
        r = error_response()
        assert r.status_code == 400
        body = r.body.decode()
        assert '"success":false' in body

    def test_with_errors(self):
        r = error_response(status_code=422, code="VAL", message="Bad input",
                           errors=[{"field": "name", "message": "required"}])
        assert r.status_code == 422
        body = r.body.decode()
        assert '"errors"' in body

    def test_custom_status(self):
        r = error_response(status_code=503)
        assert r.status_code == 503


class TestPaginatedResponse:
    def test_first_page(self):
        r = paginated_response(data=["a", "b"], total_count=10, page=1, per_page=5)
        assert r.data == ["a", "b"]
        m = r.meta["pagination"]
        assert m["page"] == 1
        assert m["per_page"] == 5
        assert m["total_count"] == 10
        assert m["total_pages"] == 2
        assert m["has_next"] is True
        assert m["has_prev"] is False

    def test_middle_page(self):
        r = paginated_response(data=[], total_count=50, page=3, per_page=10)
        m = r.meta["pagination"]
        assert m["total_pages"] == 5
        assert m["has_next"] is True
        assert m["has_prev"] is True

    def test_last_page(self):
        r = paginated_response(data=[], total_count=10, page=2, per_page=5)
        m = r.meta["pagination"]
        assert m["has_next"] is False
        assert m["has_prev"] is True

    def test_single_page(self):
        r = paginated_response(data=["x"], total_count=1, page=1, per_page=20)
        m = r.meta["pagination"]
        assert m["total_pages"] == 1
        assert m["has_next"] is False
        assert m["has_prev"] is False

    def test_exact_divisible(self):
        r = paginated_response(data=[], total_count=20, page=2, per_page=10)
        assert r.meta["pagination"]["total_pages"] == 2

    def test_round_up(self):
        r = paginated_response(data=[], total_count=11, page=1, per_page=10)
        assert r.meta["pagination"]["total_pages"] == math.ceil(11 / 10)


class TestShortcutResponders:
    def test_list_response(self):
        r = list_response(["a", "b"], message="ok")
        assert r.data == ["a", "b"]
        assert r.message == "ok"

    def test_detail_response(self):
        r = detail_response({"id": 1}, message="found")
        assert r.data == {"id": 1}
        assert r.message == "found"

    def test_delete_response(self):
        r = delete_response()
        assert r.data is None
        assert r.message == "Resource deleted successfully"

    def test_create_response(self):
        r = create_response({"id": 42}, message="created")
        assert r.data == {"id": 42}
        assert r.message == "created"

    def test_update_response(self):
        r = update_response({"id": 1, "name": "new"}, message="updated")
        assert r.data == {"id": 1, "name": "new"}
        assert r.message == "updated"


class TestErrorShortcutResponders:
    def test_validate_error_response(self):
        r = validate_error_response([{"field": "name", "message": "req"}])
        assert r.status_code == 422

    def test_not_found_response(self):
        r = not_found_response()
        assert r.status_code == 404

    def test_unauthorized_response(self):
        r = unauthorized_response()
        assert r.status_code == 401

    def test_forbidden_response(self):
        r = forbidden_response()
        assert r.status_code == 403

    def test_rate_limit_exceeded_response(self):
        r = rate_limit_exceeded_response()
        assert r.status_code == 429

    def test_server_error_response(self):
        r = server_error_response()
        assert r.status_code == 500

    def test_bad_request_response(self):
        r = bad_request_response()
        assert r.status_code == 400

    def test_method_not_allowed_response(self):
        r = method_not_allowed_response()
        assert r.status_code == 405

    def test_not_implemented_response(self):
        r = not_implemented_response()
        assert r.status_code == 501

    def test_conflict_response(self):
        r = conflict_response()
        assert r.status_code == 409

    def test_bad_gateway_response(self):
        r = bad_gateway_response()
        assert r.status_code == 502

    def test_service_unavailable_response(self):
        r = service_unavailable_response()
        assert r.status_code == 503

    def test_internal_error_response(self):
        r = internal_error_response()
        assert r.status_code == 500

    def test_unknown_error_response(self):
        r = unknown_error_response()
        assert r.status_code == 500


class TestHealthResponders:
    def test_health_check_response(self):
        r = health_check_response()
        assert r.data["status"] == "ok"
        assert r.message == "Service is healthy"

    def test_readiness_check_response(self):
        r = readiness_check_response()
        assert r.data["status"] == "ready"
        assert r.message == "Service is ready to accept requests"
