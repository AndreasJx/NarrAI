from pathlib import Path
from typing import Protocol

from .models import Artifact, GenerationResult, PublishRequest, PublishResult


class LLMProvider(Protocol):
    def generate(self, topic: str, audience: str, context: str, duration_seconds: int) -> GenerationResult: ...


class ResearchProvider(Protocol):
    def research(self, topic: str) -> GenerationResult: ...


class VoiceProvider(Protocol):
    def synthesize(self, text: str) -> Artifact: ...


class AvatarProvider(Protocol):
    def create(self, speech: Artifact) -> Artifact: ...


class MediaProvider(Protocol):
    def search(self, query: str) -> list[Artifact]: ...


class StorageProvider(Protocol):
    def put(self, source: Path, key: str) -> Artifact: ...


class Publisher(Protocol):
    def publish(self, request: PublishRequest) -> PublishResult: ...
