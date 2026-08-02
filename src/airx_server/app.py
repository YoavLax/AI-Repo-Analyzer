"""FastAPI application factory (plan-v3-codecompass.md §3).

FastAPI is imported lazily inside `create_app` so the base library install
never needs it. Run with:

    uvicorn airx_server.app:app --host 0.0.0.0 --port 8080

NOTE: no `from __future__ import annotations` here — FastAPI resolves the
factory-local Pydantic model and `Request` annotations at runtime, and
stringified annotations for factory-local names break that resolution
(the body model silently degrades to a required query parameter).
"""
import asyncio
import functools

from airx import __version__
from airx.ingest import Fetcher
from airx_server import service
from airx_server.config import Settings


def create_app(settings: Settings | None = None, fetcher: Fetcher | None = None):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    settings = settings if settings is not None else Settings.from_env()
    # An asyncio semaphore, awaited on the event loop: a blocking
    # `threading.Semaphore` in a sync endpoint parks a worker from Starlette's
    # shared 40-thread pool for the whole wait, so a burst of analyses would
    # starve /api/health and get the pod killed by its liveness probe.
    #
    # An asyncio.Semaphore binds to the loop that first awaits it, so it is
    # keyed by loop: one app object served from two loops (tests, embedding)
    # must not raise "bound to a different event loop".
    gates: dict[object, asyncio.Semaphore] = {}

    def _get_gate() -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        gate = gates.get(loop)
        if gate is None:
            gate = asyncio.Semaphore(settings.max_concurrent_analyses)
            gates[loop] = gate
        return gate

    app = FastAPI(title="AgentCompass", version=__version__, docs_url=None, redoc_url=None)

    class AnalyzeRequest(BaseModel):
        source: str | None = None
        ref: str | None = None
        path: str | None = None

    def _error(status: int, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": status, "message": message}})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/version")
    def version() -> dict:
        return {
            "version": __version__,
            "local_mode": settings.allow_local_paths and settings.local_repos_root is not None,
        }

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Keep every error response on the documented {"error": {...}} shape;
        # FastAPI's default {"detail": [...]} body would reach the SPA's error
        # mapper as an unrecognized payload.
        return _error(400, "Invalid request body: expected {'source': str} or {'path': str}.")

    @app.post("/api/analyze")
    async def analyze(request: AnalyzeRequest):
        if bool(request.source) == bool(request.path):
            return _error(400, "Provide exactly one of 'source' (GitHub URL) or 'path' (local mode).")
        try:
            await asyncio.wait_for(_get_gate().acquire(), timeout=120)
        except (asyncio.TimeoutError, TimeoutError):
            return _error(503, "The server is at capacity; try again shortly.")
        try:
            if request.source:
                work = functools.partial(
                    service.analyze_remote,
                    request.source,
                    request.ref,
                    fetcher=fetcher,
                    max_fetch_files=settings.max_fetch_files,
                    max_file_bytes=settings.max_file_bytes,
                    max_total_bytes=settings.max_total_bytes,
                )
            else:
                work = functools.partial(service.analyze_local, request.path, settings)
            # The pipeline is pure and CPU-bound: run it off the event loop.
            return await asyncio.get_running_loop().run_in_executor(None, work)
        except service.ServiceError as exc:
            return _error(exc.status, exc.message)
        finally:
            _get_gate().release()

    static_dir = settings.static_dir
    if static_dir is not None and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        index_html = static_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str, request: Request):
            if full_path.startswith("api/"):
                return _error(404, "Not found.")
            candidate = (static_dir / full_path).resolve()
            if (
                full_path
                and candidate.is_relative_to(static_dir)
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


_APP = None


def __getattr__(name: str):
    # `uvicorn airx_server.app:app` — build the app on first attribute access
    # so plain `import airx_server.app` stays FastAPI-free. Cached: repeated
    # access must return one app (and therefore one concurrency gate), not a
    # fresh instance per import site.
    global _APP
    if name == "app":
        if _APP is None:
            _APP = create_app()
        return _APP
    raise AttributeError(name)
