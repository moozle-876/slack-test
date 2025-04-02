import asyncio
import logging
import os

from src.store import Base
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv
from slack_sdk.oauth.installation_store.sqlalchemy import (
    AsyncSQLAlchemyInstallationStore,
)
from slack_sdk.oauth.state_store.sqlalchemy import AsyncSQLAlchemyOAuthStateStore

# Configure logging first
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


async def create_tables():
    load_dotenv()
    db_url = os.getenv("POSTGRES_SERVER")
    if db_url is None:
        logging.error("Please set POSTGRES_SERVER to migrate")
        return

    # Create engine inside the async function to ensure proper event loop context
    engine = create_async_engine(db_url, pool_size=20, max_overflow=10)

    installation_store = AsyncSQLAlchemyInstallationStore(
        client_id="",
        engine=engine,
    )
    state_store = AsyncSQLAlchemyOAuthStateStore(
        expiration_seconds=600,
        engine=engine,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(installation_store.metadata.create_all)
        await conn.run_sync(state_store.metadata.create_all)
        logging.info("Migration successful")

    await engine.dispose()  # Cleanly dispose the engine


if __name__ == "__main__":
    # Use asyncio.run() only once at the top level
    asyncio.run(create_tables())
