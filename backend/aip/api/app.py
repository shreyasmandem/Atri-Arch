"""FastAPI application.

Boots with zero configuration: creates its database, seeds the retrieval corpus,
provisions a demo tenant, and serves both the JSON API and the embeddable
widget. That matters for the product claim - an architecture practice must be
able to try this without a procurement process, a cloud account or a card.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from aip import __version__
from aip.api.routers import admin, design, imports, plans, system
from aip.core.config import get_settings
from aip.core.llm import shutdown_router
from aip.core.logging import configure_logging, get_logger, log_event, set_trace_id
from aip.db.session import dispose_database, init_database, session_scope

logger = get_logger("aip.api")

DESCRIPTION = """
**Architect Intelligence Platform** - an explainable multi-agent AI framework for
architectural design, interior planning, Vastu analysis, cost prediction and
client-centric automation.

Design proposals are produced by a committee of independent critics rather than a
single model. Ten of them are analytical: they compute daylight, ventilation,
privacy, circulation, accessibility, statutory compliance, structure, Vastu and
cost exactly, from the geometry, at no cost and in microseconds. Three are
generative and supply the judgement that resists formalisation. A Pareto and
reliability-weighted-Borda consensus reconciles them, and every verdict is
traceable to its evidence.

All model access runs on free tiers or local inference. `total_model_cost_usd`
is an invariant the test-suite asserts is exactly zero.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    problems = settings.validate_production()
    if problems:
        for problem in problems:
            log_event(logger, "config.invalid", level=40, problem=problem)
        raise RuntimeError(
            "Refusing to start in production with an unsafe configuration: "
            + "; ".join(problems)
        )

    await init_database()
    async with session_scope() as db:
        from aip.api.security import ensure_demo_firm

        await ensure_demo_firm(db)

    # Warm the retrieval index so the first design request is not slowed by it.
    try:
        from aip.rag.store import get_index

        index = get_index()
        log_event(logger, "corpus.ready", documents=index.size)
    except Exception as exc:  # noqa: BLE001 - retrieval is an enhancement
        log_event(logger, "corpus.unavailable", level=30, error=str(exc))

    log_event(
        logger, "app.started",
        version=__version__, environment=settings.environment,
        providers=settings.configured_providers(),
    )
    try:
        yield
    finally:
        await shutdown_router()
        await dispose_database()
        log_event(logger, "app.stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id", "X-Response-Time-Ms"],
        max_age=600,
    )

    @app.middleware("http")
    async def trace_and_time(request: Request, call_next):
        trace_id = set_trace_id(request.headers.get("X-Trace-Id"))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log_event(
                logger, "request.failed", level=40,
                method=request.method, path=request.url.path, ms=round(elapsed, 1),
            )
            raise
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"
        if request.url.path not in {"/health", f"{settings.api_prefix}/health"}:
            log_event(
                logger, "request",
                method=request.method, path=request.url.path,
                status=response.status_code, ms=round(elapsed, 1),
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        log_event(
            logger, "request.validation_failed", level=30,
            path=request.url.path, errors=str(exc.errors())[:1000],
        )
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(
            logger, "unhandled_error", level=40,
            path=request.url.path, error=f"{type(exc).__name__}: {exc}",
        )
        # Never leak internals to a browser-embedded caller.
        detail = str(exc) if settings.debug else "An internal error occurred."
        return JSONResponse(
            status_code=500,
            content={"detail": detail, "type": type(exc).__name__, "trace_id": set_trace_id(None)},
        )

    prefix = settings.api_prefix
    app.include_router(system.router, prefix=prefix)
    app.include_router(design.router, prefix=prefix)
    # Before plans: its fixed path /plans/import must not be swallowed by
    # the /plans/{plan_id} route.
    app.include_router(imports.router, prefix=prefix)
    app.include_router(plans.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)

    _mount_embed(app, settings)
    studio_mounted = _mount_studio(app)

    @app.get("/api", include_in_schema=False)
    async def api_root() -> dict[str, Any]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "api": prefix,
            "studio": "/" if studio_mounted else None,
            "embed_script": "/embed/aip-widget.js",
            "zero_cost": True,
        }

    @app.get("/health", include_in_schema=False)
    async def plain_health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


def _mount_studio(app: FastAPI) -> bool:
    """Serve the architect studio from the same origin as the API.

    Same-origin removes the CORS round trip and lets the studio call the API
    with a relative path, so a practice can self-host the whole platform behind
    one hostname with no reverse-proxy configuration.
    """
    from fastapi.staticfiles import StaticFiles

    studio_dir = Path(__file__).resolve().parents[3] / "frontend"
    if not (studio_dir / "index.html").exists():
        return False

    from aip.core.config import get_settings

    class _Studio(StaticFiles):
        """StaticFiles that refuses to be cached in development.

        The studio has no build step and no content hashing, so a browser that
        heuristically caches studio.js keeps serving yesterday's file after an
        edit. That failure is silent and expensive: the page looks like the code
        on disk, behaves like the code that was cached, and every conclusion
        drawn from it is wrong. In production the assets are versioned by
        deployment and cache normally.
        """

        def __init__(self, *args, no_store: bool, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.no_store = no_store

        def file_response(self, *args, **kwargs):  # type: ignore[override]
            response = super().file_response(*args, **kwargs)
            if self.no_store:
                response.headers["Cache-Control"] = "no-store, must-revalidate"
            return response

    app.mount(
        "/",
        _Studio(
            directory=str(studio_dir),
            html=True,
            no_store=get_settings().environment == "development",
        ),
        name="studio",
    )
    return True


def _mount_embed(app: FastAPI, settings) -> None:
    """Serve the embeddable widget with permissive CORS.

    The widget is loaded cross-origin by design - it runs on a practice's own
    website - so it must be cacheable and reachable from anywhere. Access control
    happens at the API key layer, not here.
    """
    embed_dir = Path(__file__).resolve().parents[3] / "embed"

    @app.get("/embed/aip-widget.js", include_in_schema=False)
    async def widget_script() -> Response:
        path = embed_dir / "aip-widget.js"
        if not path.exists():
            return Response(
                content="console.error('[AIP] widget bundle not found on this deployment');",
                media_type="application/javascript",
                status_code=404,
            )
        return Response(
            content=path.read_text(encoding="utf-8"),
            media_type="application/javascript; charset=utf-8",
            headers={
                "Cache-Control": "public, max-age=600",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.get("/embed/demo", include_in_schema=False)
    async def widget_demo() -> Response:
        path = embed_dir / "demo.html"
        if not path.exists():
            return Response(content="<h1>Demo page not found</h1>", media_type="text/html", status_code=404)
        return Response(content=path.read_text(encoding="utf-8"), media_type="text/html")


app = create_app()
