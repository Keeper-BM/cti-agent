"""Bounded school API calls. Never log request/response bodies or credentials."""

import asyncio
import json
import re

import httpx

from backend.core.errors import AppError
from backend.llm.contracts import SCHOOL_BASE_URL, ProviderReply

MAX_RESPONSE_BYTES = 256 * 1024


def configuration_issue(settings) -> str | None:
    if (
        not settings.llm_base_url
        or not settings.llm_model
        or not settings.llm_api_key.get_secret_value()
    ):
        return "학교 LLM 주소·모델·API 키를 서버 .env에 설정하세요."
    if settings.llm_base_url.rstrip("/") != SCHOOL_BASE_URL:
        return "현재 설명 기능은 등록된 학교 LLM 주소만 지원합니다."
    if not re.fullmatch(r"[A-Za-z0-9_./:-]{1,200}", settings.llm_model):
        return "LLM_MODEL 형식을 확인하세요."
    key = settings.llm_api_key.get_secret_value()
    if len(key) > 500 or not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key):
        return "LLM_API_KEY 형식을 확인하세요."
    return None


def require_configuration(settings):
    if issue := configuration_issue(settings):
        raise AppError("LLM_NOT_CONFIGURED", issue, 409)


class SchoolLLM:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def generate(self, messages: list[dict]) -> ProviderReply:
        require_configuration(self.settings)
        return asyncio.run(self._generate(messages))

    async def _generate(self, messages):
        settings = self.settings
        key = settings.llm_api_key.get_secret_value()
        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "stream": False,
            "temperature": 0.3,
            "max_tokens": settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            async with asyncio.timeout(settings.llm_timeout_seconds):
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                    timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
                ) as client:
                    async with client.stream(
                        "POST",
                        SCHOOL_BASE_URL + "/chat/completions",
                        json=payload,
                        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    ) as response:
                        if response.status_code in {401, 403}:
                            raise AppError(
                                "LLM_AUTH_FAILED", "학교 API 키 또는 사용 권한을 확인하세요.", 502
                            )
                        if response.status_code == 429:
                            raise AppError(
                                "LLM_RATE_LIMIT",
                                "학교 API 사용 한도에 도달했습니다. 잠시 후 다시 시도하세요.",
                                502,
                            )
                        if response.status_code != 200:
                            raise AppError(
                                "LLM_HTTP_ERROR", "학교 API가 요청을 처리하지 못했습니다.", 502
                            )
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise AppError(
                                    "LLM_RESPONSE_LIMIT",
                                    "모델 응답이 허용 크기를 초과했습니다.",
                                    502,
                                )
        except (TimeoutError, httpx.TimeoutException):
            raise AppError(
                "LLM_TIMEOUT", "AI 설명 응답 시간이 초과되었습니다. 기존 분석은 유지됩니다.", 502
            ) from None
        except httpx.HTTPError:
            raise AppError(
                "LLM_CONNECTION_FAILED", "학교 LLM API에 연결하지 못했습니다.", 502
            ) from None
        try:
            if key.encode("ascii") in raw:
                raise ValueError()
            data = json.loads(raw)
            choices = data["choices"]
            if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
                raise ValueError()
            message = choices[0]["message"]
            content = message.get("content")
            if (
                not isinstance(content, str)
                or not content.strip()
                or message.get("tool_calls")
                or message.get("refusal")
            ):
                raise ValueError()
            model = data.get("model")
            if model is not None and model != settings.llm_model:
                raise ValueError()
            usage = {
                k: v
                for k, v in (data.get("usage") or {}).items()
                if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and type(v) is int
                and v >= 0
            }
            return ProviderReply(content=content, model=model, usage=usage)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise AppError(
                "LLM_RESPONSE_INVALID", "모델이 완전한 설명 응답을 반환하지 않았습니다.", 502
            ) from None
