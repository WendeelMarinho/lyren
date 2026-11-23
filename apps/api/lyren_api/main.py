from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lyren_api.deps import get_settings
from lyren_api.routes import auth, chat, embeddings, health, models
from lyren_core.errors import LyrenError
from lyren_core.ids import current_request_id, new_request_id, set_request_id
from lyren_core.logging import configure_logging

REQUEST_ID_HEADER = "x-request-id"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Lyren API",
        version="0.1.0",
        description=(
            "Partially OpenAI-compatible. Implemented: /v1/models, non-streaming "
            "/v1/chat/completions and /v1/embeddings. Streaming, files and agent runs are not "
            "implemented and return an explicit error rather than a degraded response."
        ),
    )

    @app.middleware("http")
    async def _request_id(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        set_request_id(incoming or new_request_id())
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = current_request_id()
        return response

    @app.exception_handler(LyrenError)
    async def _lyren_error(_: Request, exc: LyrenError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "message": exc.message,
                    "type": exc.code,
                    "code": exc.code,
                    "detail": exc.detail,
                    "request_id": current_request_id(),
                }
            },
            headers={REQUEST_ID_HEADER: current_request_id()},
        )

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(chat.router)
    app.include_router(embeddings.router)
    app.include_router(auth.router)
    return app


app = create_app()
