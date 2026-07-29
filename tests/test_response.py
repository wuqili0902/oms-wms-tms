"""Tests for src.core.response — ApiResponse and response helpers."""

import pytest


class TestApiResponse:
    def test_init_defaults(self):
        from src.core.response import ApiResponse

        r = ApiResponse()
        assert r.success is True
        assert r.data is None
        assert r.message is None
        assert r.meta is None

    def test_init_custom(self):
        from src.core.response import ApiResponse

        r = ApiResponse(data={"id": 1}, message="ok", meta={"page": 1})
        assert r.success is True
        assert r.data == {"id": 1}
        assert r.message == "ok"
        assert r.meta == {"page": 1}

    def test_to_dict_minimal(self):
        from src.core.response import ApiResponse

        d = ApiResponse().to_dict()
        assert d == {"success": True, "data": None}

    def test_to_dict_with_message(self):
        from src.core.response import ApiResponse

        d = ApiResponse(data="x", message="done").to_dict()
        assert d == {"success": True, "data": "x", "message": "done"}

    def test_to_dict_with_meta(self):
        from src.core.response import ApiResponse

        d = ApiResponse(data=[], meta={"count": 0}).to_dict()
        assert d == {"success": True, "data": [], "meta": {"count": 0}}

    def test_to_dict_with_all(self):
        from src.core.response import ApiResponse

        d = ApiResponse(data="x", message="done", meta={"page": 1}).to_dict()
        assert d == {"success": True, "data": "x", "message": "done", "meta": {"page": 1}}

    def test_to_response(self):
        from src.core.response import ApiResponse

        resp = ApiResponse(data="ok").to_response()
        assert resp.status_code == 200
        assert resp.body == b'{"success":true,"data":"ok"}'


class TestSuccessResponse:
    def test_basic(self):
        from src.core.response import success_response

        r = success_response(data=[1, 2, 3])
        assert r.data == [1, 2, 3]
        assert r.message is None

    def test_with_message(self):
        from src.core.response import success_response

        r = success_response(data="x", message="done")
        assert r.message == "done"

    def test_with_meta(self):
        from src.core.response import success_response

        r = success_response(data="x", meta={"total": 10})
        assert r.meta == {"total": 10}


class TestErrorResponse:
    def test_basic(self):
        from src.core.response import error_response

        resp = error_response(status_code=400, code="BAD", message="bad request")
        assert resp.status_code == 400
        body = resp.body.decode()
        assert '"success":false' in body
        assert '"code":"BAD"' in body
        assert '"message":"bad request"' in body
        assert '"errors"' not in body

    def test_with_errors(self):
        from src.core.response import error_response

        errors = [{"field": "name", "message": "required"}]
        resp = error_response(status_code=422, code="VALIDATION", message="invalid", errors=errors)
        assert resp.status_code == 422
        body = resp.body.decode()
        assert '"errors"' in body
        assert '"field":"name"' in body


class TestPaginatedResponse:
    def test_first_page(self):
        from src.core.response import paginated_response

        r = paginated_response(data=["a", "b"], total_count=50, page=1, per_page=20)
        assert r.data == ["a", "b"]
        meta = r.meta["pagination"]
        assert meta == {
            "page": 1,
            "per_page": 20,
            "total_count": 50,
            "total_pages": 3,
            "has_next": True,
            "has_prev": False,
        }

    def test_last_page(self):
        from src.core.response import paginated_response

        r = paginated_response(data=["a"], total_count=41, page=3, per_page=20)
        meta = r.meta["pagination"]
        assert meta["has_next"] is False
        assert meta["has_prev"] is True

    def test_single_page(self):
        from src.core.response import paginated_response

        r = paginated_response(data=["a"], total_count=1, page=1, per_page=20)
        meta = r.meta["pagination"]
        assert meta["total_pages"] == 1
        assert meta["has_next"] is False

    def test_defaults(self):
        from src.core.response import paginated_response

        r = paginated_response(data=[], total_count=0)
        meta = r.meta["pagination"]
        assert meta["page"] == 1
        assert meta["per_page"] == 20


class TestSimpleWrappers:
    def test_list_response(self):
        from src.core.response import list_response

        r = list_response(data=[1, 2, 3], message="items")
        assert r.data == [1, 2, 3]
        assert r.message == "items"

    def test_detail_response(self):
        from src.core.response import detail_response

        r = detail_response(data={"id": 1}, message="found")
        assert r.data == {"id": 1}

    def test_delete_response(self):
        from src.core.response import delete_response

        r = delete_response()
        assert r.data is None
        assert r.message == "Resource deleted successfully"

    def test_delete_response_custom(self):
        from src.core.response import delete_response

        r = delete_response(message="removed")
        assert r.message == "removed"

    def test_create_response(self):
        from src.core.response import create_response

        r = create_response(data={"id": 1}, message="created")
        assert r.data == {"id": 1}

    def test_update_response(self):
        from src.core.response import update_response

        r = update_response(data={"id": 1})
        assert r.data == {"id": 1}


class TestValidateErrorResponse:
    def test_basic(self):
        from src.core.response import validate_error_response

        errors = [{"field": "email", "message": "invalid"}]
        resp = validate_error_response(errors=errors)
        assert resp.status_code == 422
        body = resp.body.decode()
        assert '"code":"VALIDATION_ERROR"' in body
        assert '"field":"email"' in body

    def test_custom_status(self):
        from src.core.response import validate_error_response

        resp = validate_error_response(errors=[], status_code=400)
        assert resp.status_code == 400


class TestHttpErrorHelpers:
    @pytest.mark.parametrize(
        "func_name, expected_status, expected_code, expected_msg",
        [
            ("not_found_response", 404, "NOT_FOUND", "Resource not found"),
            ("unauthorized_response", 401, "UNAUTHORIZED", "Authentication required"),
            ("forbidden_response", 403, "FORBIDDEN", "Permission denied"),
            ("rate_limit_exceeded_response", 429, "RATE_LIMIT_EXCEEDED", "Rate limit exceeded"),
            ("server_error_response", 500, "INTERNAL_ERROR", "Internal server error"),
            ("bad_request_response", 400, "BAD_REQUEST", "Bad request"),
            ("method_not_allowed_response", 405, "METHOD_NOT_ALLOWED", "Method not allowed"),
            ("not_implemented_response", 501, "NOT_IMPLEMENTED", "Not implemented"),
            ("conflict_response", 409, "CONFLICT", "Resource already exists"),
            ("bad_gateway_response", 502, "BAD_GATEWAY", "Bad gateway request"),
            ("service_unavailable_response", 503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable"),
            ("internal_error_response", 500, "INTERNAL_ERROR", "Internal server error"),
            ("unknown_error_response", 500, "UNKNOWN_ERROR", "An unexpected error occurred"),
        ],
    )
    def test_error_helpers(self, func_name, expected_status, expected_code, expected_msg):
        import src.core.response as mod

        func = getattr(mod, func_name)
        resp = func()
        assert resp.status_code == expected_status
        body = resp.body.decode()
        assert f'"code":"{expected_code}"' in body
        assert f'"message":"{expected_msg}"' in body

    def test_custom_message(self):
        from src.core.response import not_found_response

        resp = not_found_response(message="Order not found")
        body = resp.body.decode()
        assert '"message":"Order not found"' in body


class TestHealthChecks:
    def test_health_check(self):
        from src.core.response import health_check_response

        r = health_check_response()
        assert r.data["status"] == "ok"
        assert r.message == "Service is healthy"

    def test_readiness_check(self):
        from src.core.response import readiness_check_response

        r = readiness_check_response()
        assert r.data["status"] == "ready"
        assert r.message == "Service is ready to accept requests"
