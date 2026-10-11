# Deploying Atri Arch for free

One Docker image serves the API and the studio (`Dockerfile` at the repo root).

## Hugging Face Spaces (recommended: free 2 vCPU / 16 GB, no sleep limits on CPU basic)
1. Create a Space -> SDK **Docker** -> blank.
2. Push this repo to the Space (or connect GitHub). The Space README needs `sdk: docker` and `app_port: 7860` in its front matter.
3. Space Settings -> **Secrets**: `GROQ_API_KEY` (comma-separated for rotation), `GOOGLE_API_KEY`, `SECRET_KEY` (any long random string) and `CORS_ORIGINS` (your Space URL, e.g. `https://you-atri-arch.hf.space`). Production refuses to start without them.
4. Open the Space URL. Health check: `/api/v1/capabilities`.

## Render (free web service, 512 MB, sleeps when idle)
1. New -> **Blueprint** -> this repo (uses `render.yaml`).
2. Set `GROQ_API_KEY` and `GOOGLE_API_KEY` in the dashboard; `SECRET_KEY` is generated, and fix `CORS_ORIGINS` if your service URL differs.

## Notes
- Without keys the studio still runs: model critics fall back to measured reviews and the brief agent to its rules parser.
- SQLite lives in `backend/var` inside the container; it resets on redeploy. Point `DATABASE_URL` at a free Postgres (Neon/Supabase, add `asyncpg`) to keep projects.
- Never commit `backend/.env`.
- The image runs with `PUBLIC_DEMO=true`: visitors use the studio without an API key. Set it to `false` to require keys.
