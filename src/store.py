from abc import ABC, abstractmethod
import asyncio
import aiofiles
import json
from pathlib import Path
from typing import Optional
from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import insert
from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert
from typing import Optional


class AuthTokenStore(ABC):
    @abstractmethod
    async def set_token(self, user_id: str, potpie_token: str) -> None:
        """Store the auth token for a given user_id."""
        pass

    @abstractmethod
    async def get_token(self, user_id: str) -> str | None:
        """Retrieve the auth token for a given user_id."""
        pass


class ConversationMappingStore(ABC):
    @abstractmethod
    async def set_mapping(self, parent_message_id: str, conversation_id: str) -> None:
        """Store the mapping between conversation_id and channel_id."""
        pass

    @abstractmethod
    async def get_mapping(self, parent_message_id: str) -> str | None:
        """Retrieve the conversation_id for a given channel_id."""
        pass


class InMemoryAuthTokenStore(AuthTokenStore):
    def __init__(self):
        self.store = {}

    async def set_token(self, user_id: str, potpie_token: str) -> None:
        """Store the auth token for a given user_id."""
        self.store[user_id] = potpie_token

    async def get_token(self, user_id: str) -> str | None:
        """Retrieve the auth token for a given user_id."""
        return self.store.get(user_id)


class InMemoryConversationMappingStore(ConversationMappingStore):
    def __init__(self):
        self.store = {}

    async def set_mapping(self, parent_message_id: str, conversation_id: str) -> None:
        """Store the mapping between parent_message_id and channel_id."""
        self.store[parent_message_id] = conversation_id

    async def get_mapping(self, parent_message_id: str) -> str | None:
        """Retrieve the conversation_id for a given parent_message_id."""
        return self.store.get(parent_message_id)


class FileAuthTokenStore(AuthTokenStore):
    def __init__(self, file_path: str = "data/auth_tokens.json"):
        self.file_path = Path(file_path)
        self.lock = asyncio.Lock()  # For thread-safe file operations

    async def _load_data(self) -> dict:
        """Load data from the JSON file."""
        try:
            async with self.lock:
                async with aiofiles.open(self.file_path, "r") as f:
                    content = await f.read()
                    return json.loads(content) if content else {}
        except FileNotFoundError:
            return {}

    async def _save_data(self, data: dict) -> None:
        """Save data to the JSON file."""
        async with self.lock:
            async with aiofiles.open(self.file_path, "w") as f:
                await f.write(json.dumps(data, indent=2))

    async def set_token(self, user_id: str, potpie_token: str) -> None:
        data = await self._load_data()
        data[user_id] = potpie_token
        await self._save_data(data)

    async def get_token(self, user_id: str) -> Optional[str]:
        data = await self._load_data()
        return data.get(user_id)


class FileConversationMappingStore(ConversationMappingStore):
    def __init__(self, file_path: str = "data/conversation_mappings.json"):
        self.file_path = Path(file_path)
        self.lock = asyncio.Lock()

    async def _load_data(self) -> dict:
        try:
            async with self.lock:
                async with aiofiles.open(self.file_path, "r") as f:
                    content = await f.read()
                    return json.loads(content) if content else {}
        except FileNotFoundError:
            return {}

    async def _save_data(self, data: dict) -> None:
        async with self.lock:
            async with aiofiles.open(self.file_path, "w") as f:
                await f.write(json.dumps(data, indent=2))

    async def set_mapping(self, parent_message_id: str, conversation_id: str) -> None:
        data = await self._load_data()
        data[parent_message_id] = conversation_id
        await self._save_data(data)

    async def get_mapping(self, parent_message_id: str) -> Optional[str]:
        data = await self._load_data()
        return data.get(parent_message_id)


Base = declarative_base()


# SQLAlchemy Model
class AuthToken(Base):
    __tablename__ = "slack_auth_tokens"

    user_id = Column(String, primary_key=True)
    potpie_token = Column(String, nullable=False)


# SQLAlchemy Implementation
class SQLAlchemyAuthTokenStore(AuthTokenStore):
    def __init__(self, sessionmaker):
        self.sessionmaker = sessionmaker

    async def set_token(self, user_id: str, potpie_token: str) -> None:
        async with self.sessionmaker() as session:
            # Upsert operation (Update if exists, insert if not)
            stmt = (
                insert(AuthToken)
                .values(user_id=user_id, potpie_token=potpie_token)
                .on_conflict_do_update(
                    index_elements=["user_id"], set_=dict(potpie_token=potpie_token)
                )
            )
            await session.execute(stmt)  # Await the execution of the statement
            await session.commit()  # Await the commit of the transaction

    async def get_token(self, user_id: str) -> Optional[str]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                select(AuthToken).where(AuthToken.user_id == user_id)
            )
            auth_token = result.scalars().first()  # Get the first result
            return auth_token.potpie_token if auth_token else None


# SQLAlchemy Model for Conversation Mapping
class ConversationMapping(Base):
    __tablename__ = "slack_conversation_mappings"

    parent_message_id = Column(String, primary_key=True)
    conversation_id = Column(String, nullable=False)


class SQLAlchemyConversationMappingStore(ConversationMappingStore):
    def __init__(self, sessionmaker):
        self.sessionmaker = sessionmaker

    async def set_mapping(self, parent_message_id: str, conversation_id: str) -> None:
        async with self.sessionmaker() as session:
            # Upsert operation (insert or update)
            stmt = (
                insert(ConversationMapping)
                .values(
                    parent_message_id=parent_message_id, conversation_id=conversation_id
                )
                .on_conflict_do_update(
                    index_elements=["parent_message_id"],
                    set_=dict(conversation_id=conversation_id),
                )
            )
            await session.execute(stmt)  # Await the execution of the statement
            await session.commit()  # Await the commit of the transaction

    async def get_mapping(self, parent_message_id: str) -> Optional[str]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                select(ConversationMapping).where(
                    ConversationMapping.parent_message_id == parent_message_id
                )
            )
            mapping = result.scalar_one_or_none()  # Get one or none
            return mapping.conversation_id if mapping else None
