"""Unified API error contract: {code, message, detail}."""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


def not_found(entity: str, ident: str | None = None) -> ApiError:
    return ApiError("NOT_FOUND", f"{entity} 不存在" + (f": {ident}" if ident else ""), 404)


def bad_request(message: str, detail: Any = None) -> ApiError:
    return ApiError("BAD_REQUEST", message, 400, detail)
