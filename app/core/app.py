import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from loguru import logger

from app.api.main import api_router
from .config import settings


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)


app = FastAPI(
    title="Watchly",
    description="Stremio catalog addon for movie and series recommendations",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
# Static directory is at project root (3 levels up from app/core/app.py)
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Serve index.html at /configure and /{encoded}/configure
@app.get("/")
@app.get("/configure")
@app.get("/{encoded}/configure")
async def configure_page(encoded: str = None):
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Watchly API is running. Static files not found."}


app.include_router(api_router)

