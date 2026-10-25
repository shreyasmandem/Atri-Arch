"""A provider whose key is refused is parked, not retried on every call."""

import httpx

from aip.core.config import Settings
from aip.core.llm import LLMRouter, user


async def test_refused_key_parks_the_provider_after_one_call():
    calls: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})

    settings = Settings(_env_file=None, groq_api_key="gsk_test_revoked", ollama_enabled=False)
    router = LLMRouter(settings)
    router._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))

    first = await router.complete([user("hello")], interactive=True)
    asked = len(calls)
    second = await router.complete([user("hello again")], interactive=True)

    assert first.degraded and second.degraded
    assert asked == 1, "one refused call is enough to know the key is bad"
    assert len(calls) == asked, "a parked provider is not asked again"
    assert router.breaker.parked() == ["groq"]
