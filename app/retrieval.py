"""Permission-first local vector retrieval and managed corpus access."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Callable


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_'-]{2,}")
VALID_ROLES = frozenset({"sales", "engineering", "hr", "finance", "admin"})
MINIMUM_RELEVANCE = 0.08
STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "i", "in",
    "is", "it", "me", "of", "on", "or", "please", "show", "the", "this", "to", "was", "what", "when", "with", "you", "your",
})
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def tokenize(text: str) -> list[str]:
    return [word.lower() for word in TOKEN_PATTERN.findall(text) if word.lower() not in STOP_WORDS]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source_doc: str
    department: str
    allowed_roles: tuple[str, ...]
    sensitivity: str
    term_counts: Counter[str]


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float


class PermissionAwareRetriever:
    """A local vector index whose corpus and role set can be managed safely."""

    def __init__(
        self, corpus_root: Path, chunk_words: int = 115, overlap_words: int = 24,
        role_provider: Callable[[], set[str]] | None = None,
    ) -> None:
        self.corpus_root = corpus_root.resolve()
        self.chunk_words, self.overlap_words = chunk_words, overlap_words
        self.role_provider = role_provider or (lambda: set(VALID_ROLES))
        self.lock = RLock()
        self.chunks: list[Chunk] = []
        self.document_frequency: Counter[str] = Counter()
        self.total_chunks = 0
        self._corpus_fingerprint: tuple[tuple[str, int, int], ...] = ()
        self._refresh_if_changed(force=True)

    def _fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        if not self.corpus_root.exists():
            return ()
        return tuple(
            (path.relative_to(self.corpus_root).as_posix(), path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(self.corpus_root.rglob("*.md"))
        )

    def _refresh_if_changed(self, force: bool = False) -> None:
        fingerprint = self._fingerprint()
        if not force and fingerprint == self._corpus_fingerprint:
            return
        with self.lock:
            fingerprint = self._fingerprint()
            if not force and fingerprint == self._corpus_fingerprint:
                return
            chunks: list[Chunk] = []
            valid_roles = self.role_provider()
            for path in sorted(self.corpus_root.rglob("*.md")):
                metadata, body = self._read_document(path)
                roles = tuple(role.strip() for role in metadata["allowed_roles"].split(",") if role.strip())
                if not roles or any(role not in valid_roles for role in roles):
                    raise ValueError(f"Invalid allowed_roles in {path}")
                # Headings are useful in the master editor but not as an answer
                # sentence, so exclude them from the indexed response context.
                words = re.sub(r"(?m)^#{1,6}\s+.*$", "", body).split()
                step = max(1, self.chunk_words - self.overlap_words)
                for sequence, start in enumerate(range(0, len(words), step), start=1):
                    segment = " ".join(words[start:start + self.chunk_words]).strip()
                    if segment:
                        chunks.append(Chunk(
                            chunk_id=f"{path.relative_to(self.corpus_root).with_suffix('').as_posix()}#{sequence}",
                            text=segment, source_doc=path.name, department=metadata["department"],
                            allowed_roles=roles, sensitivity=metadata.get("sensitivity", "internal"),
                            term_counts=Counter(tokenize(segment)),
                        ))
            self.chunks = chunks
            self.document_frequency = Counter()
            for chunk in chunks:
                self.document_frequency.update(set(chunk.term_counts))
            self.total_chunks = len(chunks)
            self._corpus_fingerprint = fingerprint

    @staticmethod
    def _read_document(path: Path) -> tuple[dict[str, str], str]:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw.startswith("---\n"):
            raise ValueError(f"{path} must start with front matter")
        try:
            _, front_matter, body = raw.split("---\n", 2)
        except ValueError as exc:
            raise ValueError(f"{path} has invalid front matter") from exc
        metadata: dict[str, str] = {}
        for line in front_matter.strip().splitlines():
            if ":" not in line:
                raise ValueError(f"Invalid front matter line in {path}")
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
        for required in ("department", "allowed_roles"):
            if required not in metadata:
                raise ValueError(f"{path} is missing {required}")
        return metadata, body.strip()

    def _idf(self, token: str) -> float:
        return math.log((self.total_chunks + 1) / (self.document_frequency[token] + 1)) + 1.0

    def _score(self, query_terms: Counter[str], chunk: Chunk) -> float:
        dot = sum((count * self._idf(term)) * (chunk.term_counts[term] * self._idf(term)) for term, count in query_terms.items())
        query_norm = math.sqrt(sum((count * self._idf(term)) ** 2 for term, count in query_terms.items()))
        chunk_norm = math.sqrt(sum((count * self._idf(term)) ** 2 for term, count in chunk.term_counts.items()))
        return dot / (query_norm * chunk_norm) if query_norm and chunk_norm else 0.0

    def search(self, query: str, user_role: str, top_k: int = 4) -> tuple[list[SearchHit], int]:
        """Search only the permitted vector partition; ``user_role`` is mandatory."""
        self._refresh_if_changed()
        if user_role not in self.role_provider():
            raise ValueError("Unknown role")
        query_terms = Counter(tokenize(query))
        # SECURITY BOUNDARY: authorization completes before any chunk is scored.
        permitted = [chunk for chunk in self.chunks if user_role in chunk.allowed_roles]
        excluded_count = len(self.chunks) - len(permitted)
        hits = [SearchHit(chunk=chunk, score=self._score(query_terms, chunk)) for chunk in permitted]
        hits = [hit for hit in hits if hit.score >= MINIMUM_RELEVANCE]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        selected = hits[:max(1, min(top_k, 8))]
        for hit in selected:
            assert user_role in hit.chunk.allowed_roles, "PERMISSION LEAK DETECTED"
        return selected, excluded_count

    def document_catalog(self, include_body: bool = False) -> list[dict[str, object]]:
        self._refresh_if_changed()
        documents: list[dict[str, object]] = []
        for path in sorted(self.corpus_root.rglob("*.md")):
            metadata, body = self._read_document(path)
            relative_path = path.relative_to(self.corpus_root).as_posix()
            entry: dict[str, object] = {
                "path": relative_path, "source_doc": path.name, "department": metadata["department"],
                "allowed_roles": [role.strip() for role in metadata["allowed_roles"].split(",") if role.strip()],
                "sensitivity": metadata.get("sensitivity", "internal"),
                "chunks": sum(1 for chunk in self.chunks if chunk.source_doc == path.name),
            }
            if include_body:
                entry["body"] = body
            documents.append(entry)
        return documents

    def upsert_document(
        self, *, relative_path: str, department: str, allowed_roles: list[str], sensitivity: str, body: str,
    ) -> None:
        path = self._safe_document_path(relative_path)
        department = department.strip().lower()
        roles = sorted({role.strip().lower() for role in allowed_roles if role.strip()})
        if not SAFE_NAME.fullmatch(department):
            raise ValueError("Department must use lowercase letters, numbers, _ or -.")
        if not roles or any(role not in self.role_provider() for role in roles):
            raise ValueError("Every selected permission must be an existing role.")
        if sensitivity not in {"public", "internal", "restricted"}:
            raise ValueError("Invalid sensitivity.")
        if not body.strip() or len(body) > 50_000:
            raise ValueError("Document body must be between 1 and 50,000 characters.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ndepartment: {department}\nallowed_roles: {', '.join(roles)}\nsensitivity: {sensitivity}\n---\n\n{body.strip()}\n",
            encoding="utf-8",
        )
        self._refresh_if_changed(force=True)

    def delete_document(self, relative_path: str) -> None:
        path = self._safe_document_path(relative_path)
        if not path.exists():
            raise ValueError("Document not found.")
        path.unlink()
        self._refresh_if_changed(force=True)

    def _safe_document_path(self, relative_path: str) -> Path:
        try:
            normalized = PurePosixPath(relative_path.replace("\\", "/"))
        except TypeError as exc:
            raise ValueError("Invalid document path.") from exc
        if normalized.is_absolute() or ".." in normalized.parts or normalized.suffix.lower() != ".md" or len(normalized.parts) < 1:
            raise ValueError("Use a safe relative .md path, for example legal/contracts.md.")
        path = (self.corpus_root / Path(*normalized.parts)).resolve()
        try:
            path.relative_to(self.corpus_root)
        except ValueError as exc:
            raise ValueError("Document path must stay inside corpus.") from exc
        return path
