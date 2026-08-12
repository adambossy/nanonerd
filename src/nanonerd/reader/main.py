from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nanonerd.reader.api import router
from nanonerd.reader.db import engine
from nanonerd.reader.models import Base
from nanonerd.reader.stats import router as stats_router


def _web_dist() -> Path:
    override = os.environ.get("WEB_DIST")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="nano::nerd reader", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(stats_router)

_dist = _web_dist()
if _dist.is_dir():
    assets_dir = _dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = (_dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(_dist.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
