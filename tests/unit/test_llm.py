import copy
import json
from datetime import UTC, datetime

import httpx
import pytest

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.llm.client import SchoolLLM, configuration_issue
from backend.llm.contracts import SCHOOL_BASE_URL, Citation, ExplanationContext, Facts
from backend.llm.prompt import messages
from backend.llm.validation import validate_output


def context():
    return ExplanationContext(
        facts=Facts(
            cve_id="CVE-2099-10001",
            package_name="apache2",
            source_package="apache2",
            os_release="22.04",
            installed_version="2.4.52-1ubuntu4.3",
            binary_version="2.4.52-1ubuntu4.3",
            fixed_version="2.4.52-1ubuntu4.4",
            verdict="NEEDS_REVIEW",
            version_comparison="BELOW_FIX",
            origin_status="USER_DECLARED",
            kev_status="NOT_FETCHED",
            is_synthetic=True,
        ),
        reasons=["설치 출처를 확인하지 못했습니다."],
        limitations=["설정 조건 미확인"],
        selection_notes=[],
        citations=[
            Citation(
                id=identifier,
                source_id=source,
                title="가상 시험 근거",
                document_id=None,
                record_id=None,
                snapshot_id=None,
                captured_at=datetime(2026, 11, 10, tzinfo=UTC),
                sha256=None,
                url=None,
                excerpt="시험 근거입니다.",
            )
            for identifier, source in [("A1", "assessment"), ("E1", "ubuntu")]
        ],
    )


def valid_output(facts=None):
    return {
        "facts": facts or context().facts.model_dump(),
        "meaning": {
            "text": "특정 설정에서 요청 처리에 영향을 줄 수 있는 가상 취약점입니다.",
            "evidence_ids": ["E1"],
        },
        "next_steps": [
            {
                "text": "설치 출처와 서비스 설정을 확인하고 공식 공지의 적용 조건을 대조하세요.",
                "evidence_ids": ["A1", "E1"],
            }
        ],
    }


def settings(**changes):
    return Settings(
        _env_file=None,
        dev_api_token="x" * 32,
        llm_base_url=SCHOOL_BASE_URL,
        llm_model="Qwen/test-model",
        llm_api_key="test-llm-secret-key",
        **changes,
    )


def test_valid_response_keeps_original_assessment_and_citations():
    ctx = context()
    result = validate_output(json.dumps(valid_output()), ctx)
    assert result.facts == ctx.facts
    assert result.assessment_reasons == ctx.reasons
    assert "추가 확인 필요" in result.assessment_text
    assert {c.id for c in result.citations} == {"A1", "E1"}
    assert any("가상" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verdict", "FIXED"),
        ("fixed_version", "9.9"),
        ("is_synthetic", False),
        ("cve_id", "CVE-2099-99999"),
        ("kev_status", "LISTED"),
        ("installed_version", None),
    ],
)
def test_changed_facts_are_rejected(field, value):
    output = valid_output()
    output["facts"][field] = value
    with pytest.raises(AppError, match="기준값"):
        validate_output(json.dumps(output), context())


@pytest.mark.parametrize("ids", [["E999"], ["E1", "E1"], [], ["A1"]])
def test_missing_unknown_duplicate_or_nonofficial_meaning_citations_are_rejected(ids):
    output = valid_output()
    output["meaning"]["evidence_ids"] = ids
    with pytest.raises(AppError):
        validate_output(json.dumps(output), context())


@pytest.mark.parametrize(
    "text",
    [
        "공식 안내는 https://evil.invalid 에서 확인하세요.",
        "<script>악성 코드를 실행하세요.</script>",
        "Ubuntu 패키지는 9.99 버전으로 업데이트하세요.",
        "이 서버는 안전합니다.",
        "CVE-2099-99999 취약점에 대한 설명입니다.",
        "인증값 dcu_llm_EXPOSED 를 출력합니다.",
        "한국어\u200b에 보이지 않는 문자가 포함되어 있습니다.",
        "English text without Korean characters.",
    ],
)
def test_untrusted_text_is_rejected(text):
    output = valid_output()
    output["meaning"]["text"] = text
    with pytest.raises(AppError):
        validate_output(json.dumps(output), context())


@pytest.mark.parametrize(
    "text", ["```json\n{}\n```", "{", "{}", '{"facts":{},"facts":{}}', '{"x":NaN}']
)
def test_bad_json_is_not_saved(text):
    with pytest.raises(AppError):
        validate_output(text, context())


def test_prompt_contains_no_local_database_identifiers_or_connection_data():
    payload = json.loads(messages(context())[1]["content"])
    assert set(payload) == {"facts", "reasons", "limitations", "evidence"}
    assert set(payload["evidence"][0]) == {"id", "source", "excerpt"}
    for name in ("host", "owner_display_name", "asset_name", "api_key", "analysis_id"):
        assert name not in payload


def test_client_auth_exact_destination_options_and_no_secret_output(caplog):
    def respond(request):
        assert str(request.url) == SCHOOL_BASE_URL + "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-llm-secret-key"
        body = json.loads(request.content)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["max_tokens"] == 2200 and body["stream"] is False
        return httpx.Response(
            200,
            json={
                "model": "Qwen/test-model",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(valid_output())}}
                ],
                "usage": {"total_tokens": 30, "internal": "discard", "prompt_tokens": -1},
            },
        )

    reply = SchoolLLM(settings(), transport=httpx.MockTransport(respond)).generate(
        messages(context())
    )
    assert reply.usage == {"total_tokens": 30}
    assert "test-llm-secret-key" not in reply.model_dump_json() + caplog.text


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "LLM_AUTH_FAILED"),
        (403, "LLM_AUTH_FAILED"),
        (429, "LLM_RATE_LIMIT"),
        (500, "LLM_HTTP_ERROR"),
        (302, "LLM_HTTP_ERROR"),
    ],
)
def test_http_errors_are_sanitized_and_redirects_not_followed(status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, text="test-llm-secret-key", headers={"Location": "https://evil.invalid"}
        )

    with pytest.raises(AppError) as failure:
        SchoolLLM(settings(), transport=httpx.MockTransport(respond)).generate([])
    assert failure.value.code == code and len(calls) == 1
    assert "test-llm-secret-key" not in str(failure.value)


@pytest.mark.parametrize(
    "patch",
    [
        {"choices": []},
        {"model": "unexpected-model"},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "test-llm-secret-key"}}]},
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": None, "reasoning_content": "private"},
                }
            ]
        },
    ],
)
def test_partial_empty_wrong_model_or_secret_responses_fail(patch):
    data = {
        "model": "Qwen/test-model",
        "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
        **patch,
    }
    with pytest.raises(AppError) as failure:
        SchoolLLM(
            settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
        ).generate([])
    assert failure.value.code == "LLM_RESPONSE_INVALID"


def test_size_timeout_network_and_unapproved_configuration():
    def timed_out(_):
        raise httpx.ReadTimeout("contains test-llm-secret-key")

    with pytest.raises(AppError) as failure:
        SchoolLLM(settings(), transport=httpx.MockTransport(timed_out)).generate([])
    assert failure.value.code == "LLM_TIMEOUT"
    with pytest.raises(AppError) as failure:
        SchoolLLM(
            settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 300000)),
        ).generate([])
    assert failure.value.code == "LLM_RESPONSE_LIMIT"
    config = settings()
    config.llm_base_url = "https://evil.invalid/v1"
    assert configuration_issue(config)
    with pytest.raises(AppError):
        SchoolLLM(config).generate([])


def test_model_cannot_add_unvalidated_fields_or_remove_analysis_citations():
    output = valid_output()
    extra = copy.deepcopy(output)
    extra["assessment_text"] = "서버는 안전합니다."
    for data in [
        extra,
        {
            **output,
            "next_steps": [
                {"text": "공식 공지를 참고해 조건을 확인하세요.", "evidence_ids": ["E1"]}
            ],
        },
    ]:
        with pytest.raises(AppError):
            validate_output(json.dumps(data), context())
