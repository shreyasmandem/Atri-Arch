# Free API accounts — what to create, and why

**Short version: you do not need any of these to run the platform.**

Every analytical capability — geometry, daylight, ventilation, privacy,
circulation, accessibility, building-code compliance, Vastu reasoning, quantity
takeoff, drawings, 3D — runs entirely offline with zero configuration. Start the
server with no `.env` at all and it works.

API keys enable the three *generative* critics (design coherence, brief fidelity,
livability) and the written design rationale. Without them those run in a
labelled degraded mode; nothing silently pretends to work.

Every provider below has a genuine free tier. **None require a credit card
unless explicitly noted.** Verify current limits yourself before relying on
them — free tiers change, and this file will drift.

---

## Do this first (10 minutes, biggest effect)

### 1. Google AI Studio — the best free tier available

Highest free-tier quality, a one-million-token context, and native vision, which
matters for the "redesign this room from a photo" feature.

1. Go to **https://aistudio.google.com/apikey**
2. Sign in with a Google account
3. *Create API key* → copy it
4. Put it in `.env` as `GOOGLE_API_KEY=...`

No card. Rate limits are per-model and generous for this workload.

> **Check the shape of what you copied.** A Google AI Studio API key starts with
> `AIza` and is 39 characters. If yours starts with `AQ.` and is ~53 characters
> you have copied an **OAuth access token**, not an API key. The symptom is
> confusing, because the token authenticates successfully — listing models
> returns HTTP 200 — but every generation returns:
>
> ```
> 429 RESOURCE_EXHAUSTED
> Quota exceeded for metric: generate_content_free_tier_requests, limit: 0
> ```
>
> A limit of **zero** means no free-tier quota was ever allocated to that
> credential, not that you have used yours up. Waiting will not fix it. Go back
> to the link above and use *Create API key*, then verify:
>
> ```bash
> curl -s -H "x-goog-api-key: $GOOGLE_API_KEY" \
>   https://generativelanguage.googleapis.com/v1beta/models | head -c 200
> ```

### 2. Groq — fastest inference at zero cost

Groq's LPU hardware returns tokens fast enough that a thirteen-critic committee
feels interactive rather than batch.

1. Go to **https://console.groq.com/keys**
2. Sign up (Google or GitHub sign-in works)
3. *Create API Key* → copy it
4. `GROQ_API_KEY=...`

No card.

**Stop here if you want.** Two providers give you a working generative committee
with failover. Everything below raises ensemble diversity and resilience.

---

## Worth adding (another 10 minutes)

### 3. Cerebras — very high throughput

Useful because the committee fans out many critics at once.

- **https://cloud.cerebras.ai/** → sign up → API Keys
- `CEREBRAS_API_KEY=...`

### 4. OpenRouter — one key, many model families

The platform only ever requests model ids ending in `:free`, so spend stays at
zero. Its value here is *diversity*: DeepSeek, Qwen, Llama and Mistral through
one credential.

- **https://openrouter.ai/keys** → sign up → create key
- `OPENROUTER_API_KEY=...`

You may be asked to add credit to unlock higher free-tier limits. That is
optional; the free models work without it.

### 5. GitHub Models — free with a token you may already have

- **https://github.com/settings/tokens** → *Generate new token (fine-grained)*
- Grant the **`models: read`** permission. No repository access is needed.
- `GITHUB_TOKEN=...`

---

## Optional extras

| Provider | Where | Env var | Why bother |
|---|---|---|---|
| NVIDIA NIM | https://build.nvidia.com/ | `NVIDIA_API_KEY` | Free credits, hosts DeepSeek-R1 and Qwen-VL |
| Mistral | https://console.mistral.ai/api-keys | `MISTRAL_API_KEY` | Free experimental tier; Pixtral for vision |
| Together | https://api.together.ai/settings/api-keys | `TOGETHER_API_KEY` | A few genuinely free endpoints |
| Hugging Face | https://huggingface.co/settings/tokens | `HUGGINGFACE_API_KEY` | Monthly free inference credits; also the free image backend |

---

## Local models — free forever, no account at all

If you would rather run nothing through a third party (client data, offline
studio, air-gapped review), install Ollama:

1. **https://ollama.com/download**
2. `ollama pull qwen3:8b` and `ollama pull gemma3:12b`
3. Leave `OLLAMA_ENABLED=true` (the default)

Unlimited, private, permanently free. Slower and weaker than the hosted free
tiers, but it never leaves your machine.

**If you do not have Ollama installed, set `OLLAMA_ENABLED=false`.** Otherwise
the router attempts a connection on every generative call, discovers nothing is
listening, and the circuit breaker has to park it — measurable latency for no
benefit.

---

## Putting it together

Create `.env` in the repository root:

```dotenv
# Two keys is enough to start.
GOOGLE_API_KEY=your_google_ai_studio_key
GROQ_API_KEY=your_groq_key

# Add these for better ensemble diversity.
# CEREBRAS_API_KEY=
# OPENROUTER_API_KEY=
# GITHUB_TOKEN=
# NVIDIA_API_KEY=
# MISTRAL_API_KEY=

# Set false unless the Ollama daemon is actually running.
OLLAMA_ENABLED=false
```

Check it worked:

```bash
curl http://127.0.0.1:8000/api/v1/providers
```

The response tells you how many providers are live, your ensemble diversity
score, and what to do next. `/api/v1/health` reports `degraded_mode` and the
running cost, which should always be `0.0`.

---

## Why more than one provider

The critic committee's value comes from **independence**. Two critics running on
the same weights make correlated mistakes, so their agreement carries no
information. The router deliberately spreads generative critics across different
model *families* before it reuses one — see `diversified()` in
`aip/core/providers.py`.

One provider: the pipeline works, but the three generative critics are really
one opinion wearing three hats.
Two to three: genuine independence, plus failover when a free tier is exhausted.
Four or more: the committee stays available even when several tiers rate-limit
at once.

---

## Production deployment

For anything client-facing, set these too:

```dotenv
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<64+ random characters>
CORS_ORIGINS=https://your-practice.example,https://www.your-practice.example
DATABASE_URL=postgresql+asyncpg://user:pass@host/aip
```

The application **refuses to start** in production with a default secret key,
debug enabled, or a wildcard CORS policy. That is intentional: those three
misconfigurations are how embedded widgets leak data, and a loud failure at boot
is better than a quiet one in front of a client.

---

## What no key will buy you

Photorealistic interior renders need an image provider, which is not wired in by
default. The interior engine generates render-ready prompts built from the
*solved* layout — the actual furniture, palette and orientation — so they are
usable with any image service you choose to add. The layout, schedule, materials
and costs are computed locally and do not depend on it.
