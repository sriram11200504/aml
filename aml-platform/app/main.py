"""
AML Platform – FastAPI application entry point.
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
from .routers.ingest import router as ingest_router
from .routers.aml import router as aml_router
from .routers.ws import router as ws_router
from .worker import score_worker, monitor_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="AML Platform API",
    version="1.0.0",
    description="AML monitoring platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(aml_router)
app.include_router(ws_router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    # Seed bank registration
    from .database import AsyncSessionLocal
    from .models import BankRegistration
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(BankRegistration).where(BankRegistration.bank_id == "fakebank-01")
        )
        if not existing.scalar_one_or_none():
            session.add(BankRegistration(bank_id="fakebank-01", name="Fake Bank"))
            await session.commit()

    asyncio.create_task(score_worker())
    asyncio.create_task(monitor_worker())
    logger.info("AML Platform API started on port %d", settings.port)


@app.get("/")
@app.get("/dashboard")
async def dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AML Platform API is running. Visit /docs for API schema."}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aml-platform-api", "version": "1.0.0"}
