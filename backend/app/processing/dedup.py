"""Duplicate detection: exact, normalized and similarity-based."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.neighbors import NearestNeighbors

from app.processing.embeddings import semantic_vectors
from app.processing.text import normalize_text, sha256


@dataclass
class DedupItem:
    key: str
    text: str
    priority: int = 0  # higher = preferred as group representative (e.g. has observed failure)


@dataclass
class DedupResult:
    key: str
    duplicate_of: str | None
    method: str | None  # exact | normalized | semantic
    score: float
    group_size: int
    normalized_hash: str


@dataclass
class DedupConfig:
    similarity_threshold: float = 0.90
    use_semantic: bool = True
    use_embeddings: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def deduplicate(items: list[DedupItem], cfg: DedupConfig | None = None) -> tuple[dict[str, DedupResult], str]:
    """Return per-key results and the name of the similarity backend used."""
    cfg = cfg or DedupConfig()
    n = len(items)
    if n == 0:
        return {}, "none"
    uf = _UnionFind(n)
    method: dict[int, str] = {}
    score: dict[int, float] = {}

    exact: dict[str, int] = {}
    norm: dict[str, int] = {}
    norm_texts = [normalize_text(it.text) for it in items]
    norm_hashes = [sha256(t) for t in norm_texts]
    for i, it in enumerate(items):
        h = sha256(it.text)
        if h in exact:
            uf.union(exact[h], i)
            method[i], score[i] = "exact", 1.0
            continue
        exact[h] = i
        if norm_texts[i] and norm_hashes[i] in norm:
            uf.union(norm[norm_hashes[i]], i)
            method[i], score[i] = "normalized", 1.0
            continue
        norm.setdefault(norm_hashes[i], i)

    backend = "disabled"
    candidates = [i for i in range(n) if i not in method and norm_texts[i]]
    if cfg.use_semantic and len(candidates) > 1:
        texts = [norm_texts[i] for i in candidates]
        matrix, backend = semantic_vectors(texts, cfg.use_embeddings, cfg.embedding_model)
        radius = max(0.0, 1.0 - cfg.similarity_threshold)
        nn = NearestNeighbors(radius=radius, metric="cosine", algorithm="brute")
        nn.fit(matrix)
        dists, idxs = nn.radius_neighbors(matrix, return_distance=True)
        for row, (drow, irow) in enumerate(zip(dists, idxs, strict=True)):
            a = candidates[row]
            for d, col in zip(drow, irow, strict=True):
                b = candidates[int(col)]
                if b == a:
                    continue
                sim = float(1.0 - d)
                uf.union(a, b)
                later = max(a, b)
                if later not in method:
                    method[later] = "semantic"
                if method.get(later) == "semantic":
                    score[later] = max(score.get(later, 0.0), round(sim, 4))

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    results: dict[str, DedupResult] = {}
    for members in groups.values():
        rep = max(members, key=lambda i: (items[i].priority, -i))
        for i in members:
            is_rep = i == rep
            m = None if is_rep else method.get(i, "semantic")
            results[items[i].key] = DedupResult(
                key=items[i].key,
                duplicate_of=None if is_rep else items[rep].key,
                method=m,
                score=0.0 if is_rep else score.get(i, 1.0),
                group_size=len(members),
                normalized_hash=norm_hashes[i],
            )
    return results, backend
