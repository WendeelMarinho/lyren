from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Capability(StrEnum):
    CHAT = "CHAT"
    TEXT_EMBEDDINGS = "TEXT_EMBEDDINGS"
    TEXT_RERANK = "TEXT_RERANK"


class ApiFormat(StrEnum):
    GENERIC = "GENERIC"
    COHERE = "COHERE"


class Availability(StrEnum):
    """Why a model is or is not callable, established by probe — never by catalog metadata."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_FOUND = "not_found"
    QUOTA_ZERO = "quota_zero"


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    vendor: str
    provider: str
    api_format: ApiFormat
    pinned_version: str
    capabilities: frozenset[Capability]
    availability: Availability = Availability.UNVERIFIED
    verified_at: date | None = None
    embedding_dimensions: int | None = None
    max_context_tokens: int | None = None
    bills: bool = True
    note: str = ""

    @property
    def callable_now(self) -> bool:
        return self.availability is Availability.VERIFIED


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[Message, ...]
    max_output_tokens: int = 1024
    temperature: float = 0.0
    stop: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ChatResponse:
    model_id: str
    text: str
    finish_reason: str
    usage: Usage = field(default_factory=Usage)
    from_cache: bool = False


@runtime_checkable
class ChatProvider(Protocol):
    name: str

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse: ...
