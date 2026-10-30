"""FastAPI app: GET /healthz and POST /ask only. Read-only, no write path."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .index import DocsIndex
from .model import ModelClient, build_model
from .ratelimit import RateLimiter

log = logging.getLogger("docs_assistant")

ABSTAIN_MESSAGE = (
    "I could not find a page in the published documentation that answers this question."
)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def _error_response(err: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=err.status,
        content={"error": {"code": err.code, "message": err.message}},
        headers=err.headers,
    )


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1)


class Citation(BaseModel):
    url: str
    title: str


class AskResponse(BaseModel):
    answer: str
    abstained: bool
    citations: list[Citation]


def client_key(request: Request, trusted_hops: int) -> str:
    """Peer address, or the Nth-from-right X-Forwarded-For entry when proxies are trusted."""
    if trusted_hops > 0:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]
    return request.client.host if request.client else "unknown"


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "request_too_large", "Request body is too large.")
    buf = bytearray()
    async for part in request.stream():
        buf.extend(part)
        if len(buf) > limit:
            raise ApiError(413, "request_too_large", "Request body is too large.")
    return bytes(buf)


def create(
    settings: Settings | None = None,
    model: ModelClient | None = None,
    index: DocsIndex | None = None,
) -> FastAPI:
    cfg = settings or Settings()  # type: ignore[call-arg]  # site_dir comes from the environment
    docs_index = index or DocsIndex.from_site_dir(cfg.site_dir, cfg.docs_base_url)
    llm = model or build_model(cfg)
    limiter = RateLimiter(
        cfg.rate_limit_requests, cfg.rate_limit_window_seconds, cfg.max_tracked_clients
    )

    app = FastAPI(
        title="NeuroSphere docs assistant", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error_response(exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error_response(ApiError(exc.status_code, code, "Request not allowed."))

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "chunks": len(docs_index.chunks)}

    @app.post("/ask", response_model=AskResponse)
    async def ask(request: Request) -> AskResponse:  # pyright: ignore[reportUnusedFunction]
        retry = limiter.check(client_key(request, cfg.trusted_proxy_hops))
        if retry is not None:
            raise ApiError(429, "rate_limited", "Too many requests.", {"Retry-After": str(retry)})
        raw = await _read_body(request, cfg.max_body_bytes)
        try:
            body = AskRequest.model_validate_json(raw)
        except ValidationError as exc:
            raise ApiError(422, "invalid_request", 'Body must be {"question": string}.') from exc
        question = body.question.strip()
        if not question or len(question) > cfg.max_question_chars:
            raise ApiError(
                422, "invalid_request", f"Question must be 1-{cfg.max_question_chars} characters."
            )

        hits = docs_index.search(question, cfg.top_k)
        supported = [h for h in hits if h.score >= cfg.min_score and h.coverage >= cfg.min_coverage]
        # Privacy: log only length and a short hash, never the prompt text.
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
        log.info("ask len=%d sha256=%s abstained=%s", len(question), digest, not supported)
        if not supported:
            return AskResponse(answer=ABSTAIN_MESSAGE, abstained=True, citations=[])

        passages = [h.chunk for h in supported]
        answer = await llm.generate(question, passages)
        seen: set[str] = set()
        citations: list[Citation] = []
        for p in passages:
            if p.url not in seen:
                seen.add(p.url)
                citations.append(Citation(url=p.url, title=p.page_title or p.heading))
        return AskResponse(answer=answer, abstained=False, citations=citations)

    return app
