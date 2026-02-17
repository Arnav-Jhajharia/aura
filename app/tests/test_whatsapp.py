"""Tests for tools/whatsapp.py — WhatsAppResult, parse_wa_response, client lifecycle."""

from tools.whatsapp import (
    WhatsAppResult,
    _get_client,
    close_client,
    parse_wa_response,
)


class TestParseWaResponse:
    def test_success(self):
        resp = {"messages": [{"id": "wamid.abc123"}]}
        result = parse_wa_response(resp, 200)
        assert result.success is True
        assert result.wa_message_id == "wamid.abc123"

    def test_error(self):
        resp = {"error": {"code": 100, "message": "Invalid parameter"}}
        result = parse_wa_response(resp, 400)
        assert result.success is False
        assert result.error_code == 100
        assert result.error_message == "Invalid parameter"
        assert result.retryable is False

    def test_rate_limit_retryable(self):
        resp = {"error": {"code": 130472, "message": "Rate limit hit"}}
        result = parse_wa_response(resp, 429)
        assert result.success is False
        assert result.retryable is True

    def test_unsupported_type_fallback(self):
        resp = {"error": {"code": 131051, "message": "Unsupported message type"}}
        result = parse_wa_response(resp, 400)
        assert result.success is False
        assert result.fallback_format == "text"

    def test_empty_response(self):
        result = parse_wa_response({}, 200)
        assert result.success is False
        assert result.error_message == "unknown response structure"

    def test_malformed(self):
        result = parse_wa_response("not a dict", 200)
        assert result.success is False
        assert result.error_message == "malformed response"

    def test_non_200_no_body(self):
        result = parse_wa_response({}, 500)
        assert result.success is False
        assert result.retryable is True


class TestWhatsAppResult:
    def test_defaults(self):
        r = WhatsAppResult()
        assert r.success is False
        assert r.wa_message_id is None
        assert r.retryable is False
        assert r.fallback_format is None

    def test_full_error(self):
        r = WhatsAppResult(
            success=False, error_code=130472,
            error_message="Rate limit", retryable=True,
        )
        assert r.error_code == 130472
        assert r.retryable is True


class TestClientLifecycle:
    async def test_get_client_creates(self):
        client = _get_client()
        assert client is not None
        assert not client.is_closed
        await close_client()

    async def test_close_client_closes(self):
        _get_client()
        await close_client()
        # After close, _get_client creates a fresh one
        client = _get_client()
        assert not client.is_closed
        await close_client()
