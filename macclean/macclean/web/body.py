from __future__ import annotations

import json
from typing import Any, Dict, List

from .errors import ApiError


class RequestBody:
    """Validated, typed access to a JSON request body."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def parse(cls, raw: bytes) -> "RequestBody":
        if not raw:
            return cls({})
        try:
            data = json.loads(raw)
        except ValueError:
            raise ApiError("The request body is not valid JSON.")
        if not isinstance(data, dict):
            raise ApiError("The request body must be a JSON object.")
        return cls(data)

    def boolean(self, key: str, default: bool) -> bool:
        value = self._value(key, default)
        if not isinstance(value, bool):
            raise ApiError(f"'{key}' must be true or false.")
        return value

    def text(self, key: str, default: str) -> str:
        value = self._value(key, default)
        if not isinstance(value, str):
            raise ApiError(f"'{key}' must be text.")
        return value

    def number(self, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self._value(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(f"'{key}' must be a number.")
        if not minimum <= value <= maximum:
            raise ApiError(f"'{key}' must be between {minimum:g} and {maximum:g}.")
        return value

    def text_list(self, key: str) -> List[str]:
        value = self._value(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ApiError(f"'{key}' must be a list of text values.")
        return value

    def _value(self, key: str, default: Any) -> Any:
        value = self._data.get(key)
        return default if value is None else value
