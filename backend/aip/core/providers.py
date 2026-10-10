"""Registry of free model providers.

This file encodes the economic core of the platform. Every entry below is a
provider with a genuine free tier (or fully local inference), reachable over an
OpenAI-compatible HTTP interface. The router in `aip.core.llm` treats this as a
capability market: it asks for a capability, this registry answers with the
candidate models ranked by quality, and the router walks the list until one
answers.

Adding a provider is a data change, not a code change. Removing your API keys
degrades quality but never breaks the platform - Ollama and the analytical
engines keep working.

Rate limits are the *documented free tier* figures and are used for local
throttling so we stay inside the free allowance rather than discovering it via
HTTP 429. They are deliberately conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from aip.core.config import Settings


class Capability(str, Enum):
    """What a model is being asked to do."""

    FAST = "fast"              # short, cheap, high-throughput turns
    REASONING = "reasoning"    # critique, arbitration, multi-constraint analysis
    LONG_CONTEXT = "long"      # whole-corpus / whole-document reasoning
    VISION = "vision"          # image understanding (room photos, plan scans)
    STRUCTURED = "structured"  # reliable JSON emission


class AuthStyle(str, Enum):
    BEARER = "bearer"
    HEADER_KEY = "header_key"
    QUERY_KEY = "query_key"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A single addressable model."""

    id: str
    provider: str
    capabilities: frozenset[Capability]
    context_window: int
    quality: float               # 0-1 routing preference within a capability
    rpm: int                     # requests / minute on the free tier
    rpd: int                     # requests / day on the free tier
    supports_json: bool = True
    supports_tools: bool = False
    notes: str = ""

    def handles(self, capability: Capability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """An OpenAI-compatible endpoint plus its credential source."""

    name: str
    base_url: str
    settings_key: str            # attribute on Settings holding the credential
    auth: AuthStyle = AuthStyle.BEARER
    auth_header: str = "Authorization"
    signup_url: str = ""
    free_tier_note: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    models: tuple[ModelSpec, ...] = ()

    def credential(self, settings: Settings) -> str:
        return str(getattr(settings, self.settings_key, "") or "").strip()

    def is_available(self, settings: Settings) -> bool:
        if self.auth is AuthStyle.NONE:
            return True
        if self.name == "ollama":
            return bool(settings.ollama_enabled)
        return bool(self.credential(settings))

    def headers(self, settings: Settings) -> dict[str, str]:
        out = {"Content-Type": "application/json", **self.extra_headers}
        key = self.credential(settings)
        if self.auth is AuthStyle.BEARER and key:
            out[self.auth_header] = f"Bearer {key}"
        elif self.auth is AuthStyle.HEADER_KEY and key:
            out[self.auth_header] = key
        return out

    def resolved_base_url(self, settings: Settings) -> str:
        if self.name == "ollama":
            return settings.ollama_base_url.rstrip("/") + "/v1"
        return self.base_url.rstrip("/")


_ALL = frozenset(Capability)
_TEXT = frozenset({Capability.FAST, Capability.REASONING, Capability.STRUCTURED})
_TEXT_LONG = _TEXT | {Capability.LONG_CONTEXT}
_TEXT_VISION = _TEXT | {Capability.VISION}


# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

GROQ = ProviderSpec(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    settings_key="groq_api_key",
    signup_url="https://console.groq.com/keys",
    free_tier_note="Free tier, no card. Fastest inference available at zero cost.",
    models=(
        ModelSpec("llama-3.3-70b-versatile", "groq", _TEXT_LONG, 131072, 0.88, 30, 1000, supports_tools=True),
        ModelSpec("openai/gpt-oss-120b", "groq", _TEXT_LONG, 131072, 0.90, 30, 1000, supports_tools=True),
        ModelSpec("openai/gpt-oss-20b", "groq", _TEXT_LONG, 131072, 0.80, 30, 1000, supports_tools=True),
        ModelSpec("qwen/qwen3-32b", "groq", _TEXT_LONG, 131072, 0.83, 60, 1000),
        ModelSpec("deepseek-r1-distill-llama-70b", "groq", frozenset({Capability.REASONING, Capability.LONG_CONTEXT}), 131072, 0.86, 30, 1000,
                  notes="Chain-of-thought distillation; strong for critic roles."),
        ModelSpec("meta-llama/llama-4-scout-17b-16e-instruct", "groq", _TEXT_VISION, 131072, 0.79, 30, 1000),
        ModelSpec("meta-llama/llama-4-maverick-17b-128e-instruct", "groq", _TEXT_VISION, 131072, 0.84, 30, 1000),
        ModelSpec("llama-3.1-8b-instant", "groq", _TEXT, 131072, 0.62, 30, 14400),
    ),
)

GOOGLE = ProviderSpec(
    name="google",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    settings_key="google_api_key",
    signup_url="https://aistudio.google.com/apikey",
    free_tier_note="Google AI Studio free tier. Best free vision + 1M context.",
    models=(
        ModelSpec("gemini-2.5-flash", "google", _ALL, 1048576, 0.92, 10, 250, supports_tools=True),
        ModelSpec("gemini-2.5-flash-lite", "google", _ALL, 1048576, 0.78, 15, 1000),
        ModelSpec("gemini-2.0-flash", "google", _ALL, 1048576, 0.85, 15, 200, supports_tools=True),
        ModelSpec("gemini-2.0-flash-lite", "google", _ALL, 1048576, 0.72, 30, 200),
        ModelSpec("gemini-2.5-pro", "google", _ALL, 1048576, 0.96, 5, 100, supports_tools=True,
                  notes="Highest free-tier quality; reserved for final arbitration."),
    ),
)

CEREBRAS = ProviderSpec(
    name="cerebras",
    base_url="https://api.cerebras.ai/v1",
    settings_key="cerebras_api_key",
    signup_url="https://cloud.cerebras.ai/",
    free_tier_note="Free tier with very high tokens/sec. Excellent for parallel critics.",
    models=(
        ModelSpec("llama-3.3-70b", "cerebras", _TEXT, 65536, 0.87, 30, 14400),
        ModelSpec("qwen-3-235b-a22b-instruct-2507", "cerebras", _TEXT_LONG, 131072, 0.91, 30, 14400),
        ModelSpec("gpt-oss-120b", "cerebras", _TEXT_LONG, 131072, 0.89, 30, 14400),
        ModelSpec("llama3.1-8b", "cerebras", _TEXT, 32768, 0.60, 30, 14400),
    ),
)

OPENROUTER = ProviderSpec(
    name="openrouter",
    base_url="https://openrouter.ai/api/v1",
    settings_key="openrouter_api_key",
    signup_url="https://openrouter.ai/keys",
    free_tier_note="Aggregator. Only ':free' model ids are used, so spend stays at zero.",
    extra_headers={
        "HTTP-Referer": "https://github.com/aip-platform",
        "X-Title": "Architect Intelligence Platform",
    },
    models=(
        ModelSpec("deepseek/deepseek-chat-v3.1:free", "openrouter", _TEXT_LONG, 163840, 0.89, 20, 50),
        ModelSpec("deepseek/deepseek-r1:free", "openrouter", frozenset({Capability.REASONING, Capability.LONG_CONTEXT}), 163840, 0.90, 20, 50),
        ModelSpec("qwen/qwen3-235b-a22b:free", "openrouter", _TEXT_LONG, 131072, 0.88, 20, 50),
        ModelSpec("meta-llama/llama-3.3-70b-instruct:free", "openrouter", _TEXT_LONG, 131072, 0.85, 20, 50),
        ModelSpec("qwen/qwen2.5-vl-72b-instruct:free", "openrouter", _TEXT_VISION, 32768, 0.83, 20, 50),
        ModelSpec("google/gemma-3-27b-it:free", "openrouter", _TEXT_VISION, 96000, 0.76, 20, 50),
        ModelSpec("mistralai/mistral-small-3.2-24b-instruct:free", "openrouter", _TEXT_VISION, 96000, 0.74, 20, 50),
    ),
)

MISTRAL = ProviderSpec(
    name="mistral",
    base_url="https://api.mistral.ai/v1",
    settings_key="mistral_api_key",
    signup_url="https://console.mistral.ai/api-keys",
    free_tier_note="Free experimental tier on La Plateforme.",
    models=(
        ModelSpec("mistral-large-latest", "mistral", _TEXT_LONG, 131072, 0.86, 20, 500, supports_tools=True),
        ModelSpec("pixtral-12b-2409", "mistral", _TEXT_VISION, 131072, 0.75, 20, 500),
        ModelSpec("mistral-small-latest", "mistral", _TEXT_LONG, 131072, 0.72, 30, 500),
    ),
)

GITHUB_MODELS = ProviderSpec(
    name="github",
    base_url="https://models.github.ai/inference",
    settings_key="github_token",
    signup_url="https://github.com/settings/tokens",
    free_tier_note="Free with any GitHub personal access token (models:read scope).",
    models=(
        ModelSpec("openai/gpt-4.1-mini", "github", _ALL, 1048576, 0.84, 10, 150, supports_tools=True),
        ModelSpec("meta/Llama-4-Scout-17B-16E-Instruct", "github", _TEXT_VISION, 128000, 0.78, 10, 150),
        ModelSpec("mistral-ai/mistral-medium-2505", "github", _TEXT_LONG, 128000, 0.79, 10, 150),
    ),
)

NVIDIA = ProviderSpec(
    name="nvidia",
    base_url="https://integrate.api.nvidia.com/v1",
    settings_key="nvidia_api_key",
    signup_url="https://build.nvidia.com/",
    free_tier_note="Free API credits for hosted NIM endpoints.",
    models=(
        ModelSpec("meta/llama-3.3-70b-instruct", "nvidia", _TEXT_LONG, 128000, 0.85, 40, 1000),
        ModelSpec("qwen/qwen2.5-vl-72b-instruct", "nvidia", _TEXT_VISION, 32768, 0.81, 40, 1000),
        ModelSpec("deepseek-ai/deepseek-r1", "nvidia", frozenset({Capability.REASONING, Capability.LONG_CONTEXT}), 128000, 0.88, 40, 1000),
    ),
)

TOGETHER = ProviderSpec(
    name="together",
    base_url="https://api.together.xyz/v1",
    settings_key="together_api_key",
    signup_url="https://api.together.ai/settings/api-keys",
    free_tier_note="Free endpoints available for selected open models.",
    models=(
        ModelSpec("meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", "together", _TEXT_LONG, 131072, 0.84, 12, 500),
        ModelSpec("deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free", "together", frozenset({Capability.REASONING}), 131072, 0.83, 12, 500),
    ),
)

HUGGINGFACE = ProviderSpec(
    name="huggingface",
    base_url="https://router.huggingface.co/v1",
    settings_key="huggingface_api_key",
    signup_url="https://huggingface.co/settings/tokens",
    free_tier_note="Monthly free inference credits; also the free image-gen backend.",
    models=(
        ModelSpec("meta-llama/Llama-3.3-70B-Instruct", "huggingface", _TEXT_LONG, 131072, 0.82, 10, 300),
        ModelSpec("Qwen/Qwen2.5-VL-72B-Instruct", "huggingface", _TEXT_VISION, 32768, 0.80, 10, 300),
    ),
)

OLLAMA = ProviderSpec(
    name="ollama",
    base_url="http://127.0.0.1:11434/v1",
    settings_key="ollama_base_url",
    auth=AuthStyle.NONE,
    signup_url="https://ollama.com/download",
    free_tier_note="Fully local. Unlimited, private, offline, permanently free.",
    models=(
        ModelSpec("qwen3:8b", "ollama", _TEXT_LONG, 40960, 0.68, 600, 1_000_000),
        ModelSpec("llama3.1:8b", "ollama", _TEXT_LONG, 131072, 0.64, 600, 1_000_000),
        ModelSpec("gemma3:12b", "ollama", _TEXT_VISION, 131072, 0.70, 600, 1_000_000),
        ModelSpec("llava:13b", "ollama", frozenset({Capability.VISION, Capability.FAST}), 32768, 0.58, 600, 1_000_000),
        ModelSpec("qwen2.5-coder:7b", "ollama", _TEXT, 32768, 0.60, 600, 1_000_000),
    ),
)


PROVIDERS: tuple[ProviderSpec, ...] = (
    GOOGLE,
    GROQ,
    CEREBRAS,
    OPENROUTER,
    NVIDIA,
    MISTRAL,
    GITHUB_MODELS,
    TOGETHER,
    HUGGINGFACE,
    OLLAMA,
)

PROVIDERS_BY_NAME: dict[str, ProviderSpec] = {p.name: p for p in PROVIDERS}


def all_models() -> list[ModelSpec]:
    return [m for p in PROVIDERS for m in p.models]


def available_providers(settings: Settings) -> list[ProviderSpec]:
    return [p for p in PROVIDERS if p.is_available(settings)]


def candidates_for(
    capability: Capability,
    settings: Settings,
    *,
    min_context: int = 0,
    exclude_providers: frozenset[str] = frozenset(),
) -> list[ModelSpec]:
    """Models that can serve `capability`, best first.

    Diversity matters for the multi-agent consensus: two critics running the same
    weights produce correlated errors, which defeats the point of an ensemble.
    The router therefore also uses this list to spread agents across *providers*,
    not just across model ids.
    """
    usable: list[ModelSpec] = []
    for provider in available_providers(settings):
        if provider.name in exclude_providers:
            continue
        for model in provider.models:
            if model.handles(capability) and model.context_window >= min_context:
                usable.append(model)
    usable.sort(key=lambda m: m.quality, reverse=True)
    return usable


def diversified(models: list[ModelSpec], count: int) -> list[ModelSpec]:
    """Pick `count` models maximising provider diversity, then quality.

    Round-robins across providers so an ensemble of N agents draws on as many
    independent model families as possible before it repeats one.
    """
    buckets: dict[str, list[ModelSpec]] = {}
    for model in models:
        buckets.setdefault(model.provider, []).append(model)
    for bucket in buckets.values():
        bucket.sort(key=lambda m: m.quality, reverse=True)

    order = sorted(buckets, key=lambda name: buckets[name][0].quality, reverse=True)
    picked: list[ModelSpec] = []
    depth = 0
    while len(picked) < count and order:
        progressed = False
        for name in order:
            bucket = buckets[name]
            if depth < len(bucket):
                picked.append(bucket[depth])
                progressed = True
                if len(picked) == count:
                    return picked
        if not progressed:
            break
        depth += 1
    return picked


def provider_setup_report(settings: Settings) -> list[dict[str, object]]:
    """Human-facing status of every provider - powers the onboarding screen."""
    rows: list[dict[str, object]] = []
    for provider in PROVIDERS:
        rows.append(
            {
                "provider": provider.name,
                "configured": provider.is_available(settings),
                "signup_url": provider.signup_url,
                "env_var": provider.settings_key.upper(),
                "free_tier": provider.free_tier_note,
                "models": len(provider.models),
                "best_quality": max((m.quality for m in provider.models), default=0.0),
                "capabilities": sorted(
                    {c.value for m in provider.models for c in m.capabilities}
                ),
            }
        )
    return rows
