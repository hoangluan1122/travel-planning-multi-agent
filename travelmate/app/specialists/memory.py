import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ..agents import AgentError, BaseAgent
from ..models import Model, ShortText


class MemoryRequest(Model):
    operation: Literal["read", "save", "forget"]
    preferences: list[ShortText] = Field(default_factory=list, max_length=20)
    confirmed: bool = Field(default=False, strict=True)
    expected_version: int = Field(default=0, ge=0, strict=True)
    ttl_days: int = Field(default=90, ge=1, le=365)

    @model_validator(mode="after")
    def operation_payload(self):
        if self.operation != "save" and self.preferences:
            raise ValueError("Only save accepts preferences")
        self.preferences = list(dict.fromkeys(self.preferences))
        return self


class MemoryReport(Model):
    preferences: list[str]
    version: int
    expires_at: datetime | None
    status: Literal["found", "empty", "saved", "forgotten"]


class MemoryConflictError(AgentError):
    pass


class MemoryConsentError(AgentError):
    pass


class MemorySpecialist(BaseAgent[MemoryRequest, MemoryReport]):
    """Trusted host supplies user identity, never an LLM or request-body user_id.

    SQLite is the local repository adapter, not a migration of the project Postgres DB.
    """

    name, input_schema, output_schema = "memory_specialist", MemoryRequest, MemoryReport

    def __init__(self, path: Path, authenticated_user_id: UUID, now=None):
        self.path = str(path)
        self.user_id = str(UUID(str(authenticated_user_id)))
        self.now = now or (lambda: datetime.now(UTC))

    async def execute(self, data, context):
        if data.operation != "read" and not data.confirmed:
            raise MemoryConsentError("Explicit confirmation required for memory changes")
        if any(not item.strip() or len(item) > 200 for item in data.preferences):
            raise AgentError("Preferences must be nonempty and at most 200 characters")
        return await asyncio.to_thread(self._transaction, data)

    def _transaction(self, data):
        import json

        now = int(self.now().timestamp())
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_preferences ("
                "user_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "version INTEGER NOT NULL, expires INTEGER NOT NULL)"
            )
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload,version,expires FROM agent_preferences WHERE user_id=?", (self.user_id,)
            ).fetchone()
            version = row[1] if row else 0
            live = bool(row and row[2] > now)
            if row and not live:
                # Erase expired content but retain the version to prevent stale writes.
                connection.execute(
                    "UPDATE agent_preferences SET payload='[]' WHERE user_id=?", (self.user_id,)
                )
            if data.operation == "read":
                result = MemoryReport(
                    preferences=json.loads(row[0]) if live else [],
                    version=version,
                    expires_at=datetime.fromtimestamp(row[2], UTC) if live else None,
                    status="found" if live else "empty",
                )
            else:
                if data.expected_version != version:
                    raise MemoryConflictError("Memory version conflict; read latest state before updating")
                preferences = list(dict.fromkeys(p.strip() for p in data.preferences))
                expires = now + data.ttl_days * 86400
                if data.operation == "forget":
                    preferences, expires = [], 0
                connection.execute(
                    "INSERT INTO agent_preferences VALUES (?,?,?,?) ON CONFLICT(user_id) "
                    "DO UPDATE SET payload=excluded.payload,version=excluded.version,expires=excluded.expires",
                    (self.user_id, json.dumps(preferences, ensure_ascii=False), version + 1, expires),
                )
                result = MemoryReport(
                    preferences=preferences,
                    version=version + 1,
                    expires_at=datetime.fromtimestamp(expires, UTC) if expires else None,
                    status="saved" if expires else "forgotten",
                )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
