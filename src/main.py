import logging
import os

from dotenv import load_dotenv

from fastapi import FastAPI, Request, Response
from slack_sdk.oauth.installation_store import FileInstallationStore
from slack_sdk.oauth.state_store import FileOAuthStateStore
from slack_sdk.oauth.installation_store.sqlalchemy import (
    AsyncSQLAlchemyInstallationStore,
)
from slack_sdk.oauth.state_store.sqlalchemy import AsyncSQLAlchemyOAuthStateStore
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from potpie_service import PotpieAPIClient
from app import build_app
from store import (
    FileAuthTokenStore,
    FileConversationMappingStore,
    SQLAlchemyAuthTokenStore,
    SQLAlchemyConversationMappingStore,
)
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.oauth.async_oauth_flow import AsyncOAuthFlow

logging.basicConfig(level=logging.DEBUG)


load_dotenv()

client_id = os.getenv("SLACK_CLIENT_ID")
if client_id == None:
    logging.error("SLACK_CLIENT_ID not set")
    exit(1)

client_secret = os.getenv("SLACK_CLIENT_SECRET")
if client_secret == None:
    logging.error("SLACK_CLIENT_SECRET not set")
    exit(1)

signing_secret = os.getenv("SLACK_SIGNING_SECRET")
if signing_secret == None:
    logging.error("SLACK_SIGNING_SECRET not set")
    exit(1)

potpie_host = os.getenv("POTPIE_HOST") or "http://localhost:8001"
potpie_client = PotpieAPIClient(potpie_host)

token_store = FileAuthTokenStore()
conversation_mapping_store = FileConversationMappingStore()
installation_store = FileInstallationStore(base_dir="./data")
state_store = FileOAuthStateStore(expiration_seconds=600, base_dir="./data/states")

db_url = os.getenv("POSTGRES_SERVER")

if db_url:
    engine = create_async_engine(
        db_url,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,  # Check connections before using them
        pool_recycle=3600,  # Recycle connections after an hour
    )
    # Create an async session factory
    session = async_sessionmaker(bind=engine)

    token_store = SQLAlchemyAuthTokenStore(session)
    conversation_mapping_store = SQLAlchemyConversationMappingStore(session)
    installation_store = AsyncSQLAlchemyInstallationStore(
        client_id=client_id,
        engine=engine,
    )
    state_store = AsyncSQLAlchemyOAuthStateStore(
        expiration_seconds=600,
        engine=engine,
    )

else:
    logging.info(f"POSTGRES_SERVER env not found, using default local file store")

app = build_app(
    signing_secret,
    client_id,
    client_secret,
    potpie_client,
    token_store,
    conversation_mapping_store,
    installation_store,
    state_store,
)

port = int(os.environ.get("PORT", 8010))
logging.info(f"Starting server on localhost:{port} ...")

fastapi_app = FastAPI()
handler = AsyncSlackRequestHandler(app)


# health check endpoint
@fastapi_app.get("/health")
async def health_check():
    return {"status": "ok"}


# handle Slack events
@fastapi_app.post("/slack/events")
async def slack_events(req: Request):
    return await handler.handle(req)


@fastapi_app.get("/slack/install")
async def slack_install(req: Request):
    return await handler.handle(req)


@fastapi_app.get("/slack/oauth_redirect")
async def slack_oauth_redirect(req: Request):
    return await handler.handle(req)
