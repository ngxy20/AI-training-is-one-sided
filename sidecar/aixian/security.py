"""Credential encryption. Windows DPAPI (user scope); Fernet fallback on other OSes.

Stored value format: ``dpapi:<base64>`` / ``fernet:<token>``. Plain JSON is accepted
only for reading legacy values, never written back.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

from . import config
from .errors import ApiError


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _to_blob(data: bytes):
    buffer = (ctypes.c_ubyte * max(1, len(data))).from_buffer_copy(data or b"\0")
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    src, keep = _to_blob(data)
    dst = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)
        _ = keep


def _dpapi_unprotect(data: bytes) -> bytes:
    src, keep = _to_blob(data)
    dst = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)
        _ = keep


def _fernet() -> Any:
    from cryptography.fernet import Fernet

    key_path = config.APP_HOME / "secret.key"
    config.APP_HOME.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


def encrypt_text(text: str) -> str:
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return "dpapi:" + base64.b64encode(_dpapi_protect(raw)).decode("ascii")
        except OSError:
            pass
    return "fernet:" + _fernet().encrypt(raw).decode("ascii")


def decrypt_text(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("dpapi:"):
        if sys.platform != "win32":
            raise ApiError("CRYPTO_UNAVAILABLE", "DPAPI 凭据只能在创建它的 Windows 用户下解密", 500)
        return _dpapi_unprotect(base64.b64decode(value[6:])).decode("utf-8")
    if value.startswith("fernet:"):
        return _fernet().decrypt(value[7:].encode("ascii")).decode("utf-8")
    return value  # legacy plaintext


def encrypt_obj(obj: Any) -> str:
    return encrypt_text(json.dumps(obj, ensure_ascii=False))


def decrypt_obj(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    text = decrypt_text(value)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ApiError("CRYPTO_UNAVAILABLE", "凭据解密失败", 500, str(exc)) from exc
    return data if isinstance(data, dict) else {"value": data}


def mask_config(obj: dict[str, Any]) -> dict[str, Any]:
    secret_keys = {"password", "passwd", "pwd", "secret", "token", "api_key", "key"}
    return {k: ("******" if any(s in k.lower() for s in secret_keys) else v) for k, v in obj.items()}
