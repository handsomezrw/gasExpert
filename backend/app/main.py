from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import time

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cases, chat, health, history, incidents, topology
from app.config import get_settings
from app.logging_config import setup_logging

setup_logging()
logger = structlog.get_logger()

_HITL_TIMEOUT_MINUTES = 15
_HITL_POLL_SECONDS = 60  # check every minute


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    Path("./data").mkdir(parents=True, exist_ok=True)

    from app.memory.database import init_db, init_engine

    init_engine()
    await init_db()

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

        # Phase 6.3.5: background HITL timeout monitor
        async def _hitl_watchdog():
            while True:
                await asyncio.sleep(_HITL_POLL_SECONDS)
                try:
                    from app.memory.database import session_factory
                    from app.memory import repository as repo

                    factory = session_factory()
                    async with factory() as db:
                        stalled = await repo.list_stalled_incidents(db, _HITL_TIMEOUT_MINUTES)
                        for inc in stalled:
                            logger.warning(
                                "hitl_timeout_escalation",
                                incident_id=inc.incident_id,
                                session_id=inc.session_id,
                                stalled_minutes=_HITL_TIMEOUT_MINUTES,
                            )
                            # Mark as escalated
                            await repo.update_incident_status(db, inc.incident_id, "escalated")
                        await db.commit()
                except Exception as exc:
                    logger.error("hitl_watchdog_error", error=str(exc))

        watchdog_task = asyncio.create_task(_hitl_watchdog())

        yield

        watchdog_task.cancel()
        logger.info("shutdown")
        from app.memory.database import engine as db_engine

        if db_engine is not None:
            await db_engine.dispose()


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
    app.include_router(topology.router, prefix="/api", tags=["topology"])
    app.include_router(incidents.router, prefix="/api", tags=["incidents"])
    app.include_router(cases.router, prefix="/api", tags=["cases"])

    return app


app = create_app()
