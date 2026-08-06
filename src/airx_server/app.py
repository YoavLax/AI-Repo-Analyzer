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
import json

from airx import __version__
from airx.ingest import Fetcher, ProgressHook
from airx.model import Platform
from airx_server import service
from airx_server.config import Settings


def create_app(settings: Settings | None = None, fetcher: Fetcher | None = None):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
        # Restricts scoring to one agent harness's rules, mirroring the CLI's
        # `--platform` flag. "all" (or omitted) scores both, as before.
        platform: str | None = None

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

    def _parse_target(request: AnalyzeRequest):
        """(platform filter, error response) — exactly one of the two is set."""
        if bool(request.source) == bool(request.path):
            return None, _error(400, "Provide exactly one of 'source' (GitHub URL) or 'path' (local mode).")
        if request.platform is not None and request.platform != "all":
            if request.platform not in ("copilot", "claude"):
                return None, _error(400, "'platform' must be one of 'copilot', 'claude', or 'all'.")
            return Platform(request.platform), None
        return None, None

    def _build_work(
        request: AnalyzeRequest,
        platform_filter: Platform | None,
        on_progress: ProgressHook | None = None,
    ):
        if request.source:
            return functools.partial(
                service.analyze_remote,
                request.source,
                request.ref,
                fetcher=fetcher,
                max_fetch_files=settings.max_fetch_files,
                max_file_bytes=settings.max_file_bytes,
                max_total_bytes=settings.max_total_bytes,
                platform=platform_filter,
                on_progress=on_progress,
            )
        # Local-path mode reads an existing directory: there is no network work
        # to count, so it reports no progress and completes in one step.
        return functools.partial(
            service.analyze_local, request.path, settings, platform=platform_filter,
        )

    @app.post("/api/analyze")
    async def analyze(request: AnalyzeRequest):
        platform_filter, invalid = _parse_target(request)
        if invalid is not None:
            return invalid
        try:
            await asyncio.wait_for(_get_gate().acquire(), timeout=120)
        except (asyncio.TimeoutError, TimeoutError):
            return _error(503, "The server is at capacity; try again shortly.")
        try:
            # The pipeline is pure and CPU-bound: run it off the event loop.
            work = _build_work(request, platform_filter)
            return await asyncio.get_running_loop().run_in_executor(None, work)
        except service.ServiceError as exc:
            return _error(exc.status, exc.message)
        finally:
            _get_gate().release()

    @app.post("/api/analyze/stream")
    async def analyze_stream(request: AnalyzeRequest):
        """Same analysis as `/api/analyze`, delivered as NDJSON with progress.

        One JSON object per line: `{"type":"progress",...}` zero or more times,
        then exactly one terminal `{"type":"result","report":{...}}` or
        `{"type":"error","error":{...}}`. The report on the result line is the
        same object `/api/analyze` returns — this endpoint exists to report
        *while* the work happens, not to change what the work produces.

        Kept separate rather than content-negotiated on `/api/analyze` so that
        endpoint's contract (one request, one JSON body, one status code) stays
        exactly as documented for API and CI callers.
        """
        platform_filter, invalid = _parse_target(request)
        if invalid is not None:
            return invalid
        # Acquired before streaming starts so being at capacity is still a real
        # 503 rather than an error buried in a 200 response body.
        try:
            await asyncio.wait_for(_get_gate().acquire(), timeout=120)
        except (asyncio.TimeoutError, TimeoutError):
            return _error(503, "The server is at capacity; try again shortly.")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_progress(phase: str, done: int, total: int) -> None:
            # Throttled to ~100 updates per phase: a 1,100-file repository would
            # otherwise spend a line per file on a bar that renders whole
            # percents, which is bandwidth for a difference nobody can see.
            if total > 0 and done not in (0, total) and done % max(1, total // 100):
                return
            # Called from the executor thread — the only loop-safe way in.
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "phase": phase, "done": done, "total": total},
            )

        def run() -> None:
            try:
                try:
                    payload = {
                        "type": "result",
                        "report": _build_work(request, platform_filter, on_progress)(),
                    }
                except service.ServiceError as exc:
                    payload = {"type": "error", "error": {"code": exc.status, "message": exc.message}}
                except Exception:
                    payload = {
                        "type": "error",
                        "error": {"code": 500, "message": "The analysis failed unexpectedly."},
                    }
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            finally:
                # In `finally` so the reader can never block forever waiting for
                # a sentinel that a BaseException skipped past.
                loop.call_soon_threadsafe(queue.put_nowait, None)

        async def lines():
            worker = loop.run_in_executor(None, run)
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield json.dumps(item, separators=(",", ":")) + "\n"
                await worker
            finally:
                # Also runs when the client disconnects mid-stream and Starlette
                # closes this generator, so an abandoned request cannot hold the
                # concurrency slot. The executor thread still finishes its
                # current analysis — threads are not cancellable.
                _get_gate().release()

        return StreamingResponse(
            lines(),
            media_type="application/x-ndjson",
            # Defeats proxy/CDN response buffering, which would hold the
            # progress lines back and deliver them all at once at the end.
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

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
