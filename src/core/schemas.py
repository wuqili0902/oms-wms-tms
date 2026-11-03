"""Request-body bases shared by the module schema files.

Moved out of ``src/tms/schemas.py`` when the auth RBAC writes needed the same
behaviour: a base that accepts the ``{"data": {...}}`` envelope every response
this API sends, and refuses keys the body did not declare.
"""

from pydantic import BaseModel, model_validator


class PayloadBody(BaseModel):
    """Base for the write bodies that accept the ``{"data": {...}}`` envelope.

    ``src/core/pagination.py`` and the response helpers hand every payload back
    wrapped in ``{"data": ...}``, so clients learn to send the same shape back
    in; these routes took a bare ``dict``, so an envelope-shaped body reached
    ``data["reason"]`` — a KeyError, and a 500 for a request whose only fault
    was the wrapper.  Both shapes are accepted here, and the field names in a
    validation error are the payload's own in either case.
    """

    @model_validator(mode="before")
    @classmethod
    def _unwrap_envelope(cls, value: object) -> object:
        if isinstance(value, dict) and "data" in value:
            inner = value["data"]
            if not isinstance(inner, dict):
                raise ValueError("data must be an object")
            return inner
        return value

    # Declaring fields is only half the contract: an undeclared key is dropped
    # silently unless extra input is refused outright.
    model_config = {"extra": "forbid", "populate_by_name": True}
