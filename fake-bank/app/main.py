"""
Fake Bank – FastAPI application entry point.
"""
import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .database import init_db
from .routers.bank import router as bank_router
from .routers.compliance import router as compliance_router
from .outbox import outbox_dispatcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Fake Bank API",
    version="1.0.0",
    description="Test bank for AML platform integration",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bank_router)
app.include_router(compliance_router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    # Seed demo data
    from .seed import seed_database
    await seed_database()
    # Start outbox dispatcher in background
    asyncio.create_task(outbox_dispatcher())
    logger.info("Fake Bank API started on port %d", settings.port)


@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Fake Bank API is running. Visit /docs for API schema."}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "fake-bank-api", "version": "1.0.0"}
