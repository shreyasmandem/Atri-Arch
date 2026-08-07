#!/usr/bin/env python
"""Verify every registered model actually answers.

Provider catalogues rot. Free-tier model ids are withdrawn without notice - the
first version of this project's registry was written from documentation and,
when finally tested against live credentials, *every* OpenRouter ':free' id in
it had been retired, and Cerebras had moved its whole free tier behind billing.
A registry that has never been executed is a list of guesses.

This sends one tiny completion to every model the registry declares and reports
what actually works, so the registry can be corrected from evidence.

    python scripts/verify_providers.py              # only configured providers
    python scripts/verify_providers.py --all        # attempt every provider
    python scripts/verify_providers.py --json       # machine-readable

Exit code is non-zero when a configured provider has no working model, which
makes this usable as a CI or pre-deploy check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from aip.core.config import get_settings  # noqa: E402
from aip.core.providers import PROVIDERS, ModelSpec, ProviderSpec  # noqa: E402

PROBE = 'Return only this JSON and nothing else: {"ok":true}'
TIMEOUT = 60.0


async def probe(
    client: httpx.AsyncClient, provider: ProviderSpec, model: ModelSpec, settings
) -> dict[str, object]:
    url = f"{provider.resolved_base_url(settings)}/chat/completions"
    started = time.perf_counter()
    row: dict[str, object] = {
        "provider": provider.name,
        "model": model.id,
        "declared_quality": model.quality,
    }
    try:
        response = await client.post(
            url,
            headers=provider.headers(settings),
            json={
                "model": model.id,
                "messages": [{"role": "user", "content": PROBE}],
                "max_tokens": 48,
            },
        )
    except Exception as exc:  # noqa: BLE001
        row |= {"ok": False, "status": 0, "detail": f"{type(exc).__name__}: {exc}"[:160]}
        return row

    row["status"] = response.status_code
    row["ms"] = round((time.perf_counter() - started) * 1000)

    if response.status_code != 200:
        detail = response.text[:200].replace("\n", " ")
        row |= {"ok": False, "detail": detail}
        # Name the common failures rather than leaving a raw body.
        if response.status_code == 402:
            row["diagnosis"] = "account requires billing; not free"
        elif response.status_code == 404:
            row["diagnosis"] = "model id withdrawn or never existed"
        elif response.status_code == 429:
            row["diagnosis"] = "rate limited or zero quota allocated"
        elif response.status_code in (401, 403):
            row["diagnosis"] = "credential rejected"
        return row

    try:
        message = response.json()["choices"][0]["message"]
        text = (message.get("content") or message.get("reasoning_content") or "").strip()
    except Exception:  # noqa: BLE001
        row |= {"ok": False, "detail": "unparseable response body"}
        return row

    row |= {"ok": bool(text), "sample": text[:70].replace("\n", " ")}
    if not text:
        row["diagnosis"] = "returned an empty completion"
    return row


async def run(check_all: bool) -> list[dict[str, object]]:
    settings = get_settings()
    targets: list[tuple[ProviderSpec, ModelSpec]] = []
    for provider in PROVIDERS:
        if not check_all and not provider.is_available(settings):
            continue
        targets.extend((provider, model) for model in provider.models)

    limits = httpx.Limits(max_connections=8)
    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
        semaphore = asyncio.Semaphore(4)

        async def guarded(pair):
            async with semaphore:
                return await probe(client, pair[0], pair[1], settings)

        return list(await asyncio.gather(*(guarded(t) for t in targets)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="probe every provider, not just configured ones")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    rows = asyncio.run(run(args.all))
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("No providers configured. Set a key in .env - see docs/API_SETUP.md.")
        return 1

    by_provider: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_provider.setdefault(str(row["provider"]), []).append(row)

    broken: list[str] = []
    for name, entries in by_provider.items():
        working = [e for e in entries if e.get("ok")]
        print(f"\n{name}  —  {len(working)}/{len(entries)} models answering")
        for entry in entries:
            mark = "ok  " if entry.get("ok") else "FAIL"
            detail = (
                f"{entry.get('ms', '?')}ms  {entry.get('sample', '')!r}"
                if entry.get("ok")
                else f"{entry.get('status')}  {entry.get('diagnosis', entry.get('detail', ''))}"
            )
            print(f"  {mark} {str(entry['model']):50s} {detail}")
        if not working:
            broken.append(name)

    total_ok = sum(1 for r in rows if r.get("ok"))
    print(f"\n{total_ok}/{len(rows)} registered models are answering.")
    if broken:
        print(f"Providers with nothing working: {', '.join(broken)}")
        print("Correct the model ids in aip/core/providers.py from this output.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
