from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.database import init_db
from app.core.logging import configure_logging
from app.services.storage import LocalFileStorage
from app.workers.queue import ThreadPoolQueue

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # POC: create tables on startup. A real deployment uses migrations.
    init_db()
    yield
    queue = getattr(app.state, "queue", None)
    if isinstance(queue, ThreadPoolQueue):
        queue.shutdown()


def create_app(*, settings: Settings | None = None, storage=None, queue=None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title="Claims Document Extraction Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.storage = storage or LocalFileStorage(settings.upload_dir)
    app.state.queue = queue or ThreadPoolQueue()

    app.include_router(router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

    return app
