"""Test d'integration des vrais providers.

Execute uniquement si une cle API est presente dans l'environnement :

    OPENAI_API_KEY=sk-... pytest -m live
"""

from __future__ import annotations

import asyncio
import os

import pytest
from agents.core.errors import ProviderError
from agents.core.llm import build_provider
from agents.core.models import Message


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY absente")
def test_openai_minimal_roundtrip() -> None:
    provider = build_provider("openai")
    response = asyncio.run(
        provider.complete(
            [Message(role="user", content="Reponds uniquement par le mot: ok")],
            max_tokens=10,
        )
    )
    assert response.text
    assert response.usage.llm_calls == 1


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY absente")
def test_anthropic_minimal_roundtrip() -> None:
    provider = build_provider("anthropic")
    response = asyncio.run(
        provider.complete(
            [Message(role="user", content="Reponds uniquement par le mot: ok")],
            max_tokens=10,
        )
    )
    assert response.text


def test_missing_key_is_explicit() -> None:
    provider = build_provider("openai", env={})
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        asyncio.run(provider.complete([Message(role="user", content="bonjour")]))
