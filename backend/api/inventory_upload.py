"""Bound JSON uploads before parsing, including requests without Content-Length."""

import json
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_INVENTORY_BYTES = 2 * 1024 * 1024
_UPLOAD_PATH = re.compile(r"^/api/v1/assets/[^/]+/inventories(?:/csv)?/?$")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-finite JSON number")


class InventoryUploadMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not _UPLOAD_PATH.fullmatch(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_INVENTORY_BYTES:
                await self.reject(scope, receive, send, 413, "파일 크기는 최대 2 MiB입니다.")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if body:
            try:
                json.loads(
                    body.decode("utf-8-sig"),
                    object_pairs_hook=_unique_keys,
                    parse_constant=_reject_constant,
                )
            except (UnicodeError, ValueError, RecursionError):
                await self.reject(
                    scope,
                    receive,
                    send,
                    422,
                    "UTF-8 JSON 파일을 확인하세요. 잘못된 문법이나 중복 필드는 허용하지 않습니다.",
                )
                return

        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def reject(scope, receive, send, status, message):
        response = JSONResponse(
            {
                "error": {
                    "code": "INVENTORY_TOO_LARGE" if status == 413 else "INVALID_INVENTORY_JSON",
                    "message": message,
                    "request_id": scope.get("state", {}).get("request_id", ""),
                    "retryable": False,
                }
            },
            status_code=status,
        )
        await response(scope, receive, send)
