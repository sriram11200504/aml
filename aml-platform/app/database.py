from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from .config import get_settings
import os

settings = get_settings()

if settings.use_sqlite:
    os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    settings.get_db_url(),
    echo=False,
    connect_args={"check_same_thread": False} if settings.use_sqlite else {},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
