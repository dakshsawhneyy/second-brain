"""Text embedders: a real local model (fastembed) and a deterministic hash embedder for tests."""

from __future__ import annotations

import hashlib
import math
import re
import time

import httpx

from . import usage
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Embeddings from the local Ollama server (loopback only): no extra download site, no cloud."""

    def __init__(self, model: str = DEFAULT_OLLAMA_EMBED_MODEL, base_url: str = DEFAULT_OLLAMA_URL,
                 client: httpx.Client | None = None):
        self.model_name = model
        self.name = f"ollama:{model}"
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started = time.monotonic()
        chars = sum(len(t) for t in texts)
        try:
            resp = self._client.post(f"{self.base_url}/api/embed",
                                     json={"model": self.model_name, "input": [t[:4000] for t in texts]})
            resp.raise_for_status()
            vectors = resp.json().get("embeddings")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise RuntimeError("Ollama returned an unexpected embedding reply")
        except Exception as e:
            usage.log_call(provider="ollama", model=self.model_name, ok=False, started=started, prompt_chars=chars,
                           kind="embed", error=type(e).__name__)
            raise
        usage.log_call(provider="ollama", model=self.model_name, ok=True, started=started, prompt_chars=chars,
                       kind="embed")
        return [[float(x) for x in v] for v in vectors]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder. For tests and offline fallback; not semantic."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in re.findall(r"\w+", text.lower()):
                vec[int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec] if norm else vec)
        return out


class FastEmbedder:
    """Local ONNX embedding model via fastembed. Downloads its own copy of the model into cache_dir."""

    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: Path | None = None):
        self.model_name = model
        self.name = f"fastembed:{model}"
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            kwargs = {"cache_dir": str(self.cache_dir)} if self.cache_dir else {}
            self._model = TextEmbedding(model_name=self.model_name, **kwargs)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._load().embed(texts)]
