from contextlib import asynccontextmanager
from pathlib import Path
import time

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, health, history
from app.config import get_settings
from app.logging_config import setup_logging

setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    Path("./data").mkdir(parents=True, exist_ok=True)

    from app.agent.graph import build_graph
    from app.memory.checkpointer import get_sqlite_checkpointer

    try:
        from app.rag.retriever import init_retriever
        rag_ready = init_retriever()
        logger.info("rag_init", ready=rag_ready)
    except Exception as exc:
        logger.warning("rag_init_skipped", error=str(exc))

    async with get_sqlite_checkpointer() as checkpointer:
        app.state.agent_graph = build_graph(checkpointer)
        logger.info(
            "startup_complete",
            model=settings.openai_model,
            langsmith=settings.langchain_tracing_v2,
        )
        yield
        logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="燃气抢险智能副驾 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        if request.url.path != "/api/health":
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                elapsed_ms=elapsed_ms,
            )
        return response

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(history.router, prefix="/api/history", tags=["history"])

    return app


app = create_app()
