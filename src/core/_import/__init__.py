"""Shared import handler utilities."""
import csv
import io
import logging
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


class ImportResult:
    """Structured result for CSV imports."""
    
    def __init__(self, success: int = 0, errors: List[Dict[str, Any]] | None = None):
        self.success = success
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "errors": self.errors,
        }


async def import_csv_handler(
    content: str | bytes,
    db: Any,  # type: ignore[misc]
    handler: Callable[[str], Tuple[ImportResult, Exception | None]],
) -> Dict[str, Any]:
    """Generic CSV import handler with validation and error tracking.

    Args:
        content: Raw CSV string or bytes (UTF-8 decoded).
        db: AsyncSession from get_db dependency.
        handler: Async callable that takes CSV text and returns (ImportResult, Exception | None).

    Returns:
        JSON dict with success count and any errors encountered.
    """
    try:
        csv_text = content.decode("utf-8") if isinstance(content, bytes) else content.strip()
    except UnicodeDecodeError as e:
        return {"success": 0, "errors": [{"row": 1, "error": f"Invalid UTF-8 encoding: {e}"}]}

    result, error = await handler(csv_text)
    if error is not None:
        logger.warning("Import handler raised: %s", error)
    return result.to_dict()
