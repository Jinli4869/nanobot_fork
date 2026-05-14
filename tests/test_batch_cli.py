from unittest.mock import patch

from eval.batch.__main__ import _build_provider_and_model
from nanobot.config.schema import Config


def test_build_provider_and_model_uses_gui_runtime_override():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "dashscope",
                    "model": "qwen3.5-plus",
                }
            },
            "providers": {
                "dashscope": {
                    "apiKey": "dash-key",
                },
                "openrouter": {
                    "apiKey": "or-key",
                    "apiBase": "https://openrouter.ai/api/v1",
                },
            },
            "gui": {
                "model": "anthropic/claude-3.7-sonnet",
                "provider": "openrouter",
            },
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider, model = _build_provider_and_model(config)

    assert model == "anthropic/claude-3.7-sonnet"
    assert provider.get_default_model() == "anthropic/claude-3.7-sonnet"
