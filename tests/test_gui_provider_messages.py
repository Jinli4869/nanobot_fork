from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import _convert_messages


def _sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "system prompt"},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abcd"},
                },
                {"type": "text", "text": "Current screen"},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tool_call_long_identifier",
                    "type": "function",
                    "function": {
                        "name": "computer_use",
                        "arguments": '{"action_type":"tap","x":100,"y":200,"relative":false}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "tool_call_long_identifier",
            "name": "computer_use",
            "content": "Executed tap",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,efgh"},
                },
                {"type": "text", "text": "Updated screen"},
            ],
        },
    ]


def test_litellm_sanitize_messages_preserves_gui_sequence() -> None:
    provider = LiteLLMProvider(default_model="openai/gpt-4o")

    sanitized = provider._sanitize_messages(_sample_messages())

    assert sanitized[1]["content"][0]["type"] == "image_url"
    assert sanitized[2]["content"] is None
    assert len(sanitized[2]["tool_calls"][0]["id"]) == 9
    assert sanitized[3]["tool_call_id"] == sanitized[2]["tool_calls"][0]["id"]


def test_azure_prepare_request_payload_preserves_multimodal_messages() -> None:
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://example.openai.azure.com",
        default_model="gpt-4o",
    )

    payload = provider._prepare_request_payload(
        "gpt-4o",
        _sample_messages(),
        tools=[{"type": "function", "function": {"name": "computer_use", "parameters": {}}}],
        tool_choice="required",
    )

    assert payload["tool_choice"] == "required"
    assert payload["messages"][1]["content"][0]["type"] == "image_url"
    assert payload["messages"][2]["content"] is None


def test_codex_convert_messages_supports_gui_message_sequence() -> None:
    system_prompt, input_items = _convert_messages(_sample_messages())

    assert system_prompt == "system prompt"
    assert input_items[0]["content"][0]["type"] == "input_image"
    assert any(item.get("type") == "function_call" for item in input_items)
    assert any(item.get("type") == "function_call_output" for item in input_items)


@pytest.mark.asyncio
async def test_custom_provider_chat_preserves_gui_multimodal_messages(monkeypatch) -> None:
    provider = CustomProvider(
        api_key="test-key",
        api_base="http://localhost:8000/v1",
        default_model="gpt-4o",
    )
    captured: dict[str, object] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=[]),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create),
        )
    )

    response = await provider.chat(
        _sample_messages(),
        tools=[{"type": "function", "function": {"name": "computer_use", "parameters": {}}}],
        tool_choice="required",
    )

    assert response.content == "ok"
    assert captured["tool_choice"] == "required"
    assert captured["messages"][1]["content"][0]["type"] == "image_url"
    assert captured["messages"][2]["content"] is None
