"""Group similar interactions with TF-IDF + K-means (default) or DBSCAN."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize


@dataclass
class ClusterItem:
    key: str
    text: str
    failed: bool = False


@dataclass
class ClusterResult:
    label: str
    top_terms: list[str]
    member_keys: list[str]
    representative_key: str
    failure_rate: float
    method: str


@dataclass
class ClusteringConfig:
    method: str = "kmeans"  # kmeans | dbscan
    n_clusters: int | None = None  # auto when None
    max_clusters: int = 12
    dbscan_eps: float = 0.6
    dbscan_min_samples: int = 3
    random_state: int = 42
    top_terms: int = 5
    lsa_components: int = 50
    extra: dict[str, object] = field(default_factory=dict)


def _choose_k(matrix: object, n: int, cfg: ClusteringConfig) -> int:
    if cfg.n_clusters:
        return max(1, min(cfg.n_clusters, n))
    # Short support-style inputs form many small topics, so allow up to ~n/4 clusters.
    upper = max(2, min(cfg.max_clusters, max(int(math.sqrt(n)) + 1, n // 4), n - 1))
    if n < 6:
        return max(1, min(2, n))
    best_k, best_score = 2, -1.0
    # Silhouette on a bounded sample keeps this cheap for large inputs.
    sample = min(n, 2000)
    for k in range(2, upper + 1):
        km = KMeans(n_clusters=k, n_init=3, random_state=cfg.random_state)
        labels = km.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        s = silhouette_score(matrix, labels, metric="cosine", sample_size=sample, random_state=cfg.random_state)
        if s > best_score:
            best_k, best_score = k, float(s)
    return best_k


def cluster_items(items: list[ClusterItem], cfg: ClusteringConfig | None = None) -> list[ClusterResult]:
    cfg = cfg or ClusteringConfig()
    usable = [it for it in items if it.text.strip()]
    if not usable:
        return []
    if len(usable) < 3:
        return [_build("all", usable, list(range(len(usable))), None, [], cfg.method)]

    # Ignore pure numbers (order ids, phone fragments) so they don't dominate topic labels.
    vec = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.9,
        sublinear_tf=True,
        token_pattern=r"(?u)\b[^\W\d_][\w'-]+\b",  # noqa: S106 - regex, not a secret
    )
    try:
        matrix = vec.fit_transform([it.text for it in usable])
    except ValueError:  # vocabulary empty after stop-word removal
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4))
        matrix = vec.fit_transform([it.text for it in usable])
    terms = np.array(vec.get_feature_names_out())

    # Latent semantic analysis: sparse TF-IDF -> dense low-rank space. K-means on raw sparse
    # TF-IDF tends to dump short, dissimilar texts into one large "misc" cluster.
    space: Any = matrix
    if matrix.shape[1] > 3 and len(usable) > 3:
        n_comp = min(cfg.lsa_components, matrix.shape[1] - 1, len(usable) - 1)
        space = normalize(TruncatedSVD(n_components=n_comp, random_state=cfg.random_state).fit_transform(matrix))

    if cfg.method == "dbscan":
        labels = DBSCAN(eps=cfg.dbscan_eps, min_samples=cfg.dbscan_min_samples, metric="cosine").fit_predict(space)
    else:
        k = _choose_k(space, len(usable), cfg)
        labels = KMeans(n_clusters=k, n_init=5, random_state=cfg.random_state).fit_predict(space)

    results: list[ClusterResult] = []
    for lab in sorted(set(int(x) for x in labels)):
        idx = [i for i, x in enumerate(labels) if int(x) == lab]
        sub = matrix[idx]
        centroid = np.asarray(sub.mean(axis=0)).ravel()  # term-space centroid for labelling
        top = [str(terms[j]) for j in centroid.argsort()[::-1][: cfg.top_terms] if centroid[j] > 0]
        name = "noise / unclustered" if lab == -1 else None
        results.append(_build(name, usable, idx, sub, top, cfg.method, centroid))
    results.sort(key=lambda r: len(r.member_keys), reverse=True)
    return results


def _build(
    name: str | None,
    usable: list[ClusterItem],
    idx: list[int],
    sub: object,
    top: list[str],
    method: str,
    centroid: np.ndarray | None = None,
) -> ClusterResult:
    rep_i = idx[0]
    if sub is not None and centroid is not None and len(idx) > 1:
        sims = np.asarray(sub @ centroid).ravel()  # type: ignore[operator]
        rep_i = idx[int(np.argmax(sims))]
    failed = sum(1 for i in idx if usable[i].failed)
    if name is None:
        name = ", ".join(top[:3]) if top else _fallback_label([usable[i].text for i in idx])
    return ClusterResult(
        label=name,
        top_terms=top,
        member_keys=[usable[i].key for i in idx],
        representative_key=usable[rep_i].key,
        failure_rate=round(failed / len(idx), 4) if idx else 0.0,
        method=method,
    )


def _fallback_label(texts: list[str]) -> str:
    words = Counter(w for t in texts for w in t.lower().split() if len(w) > 3)
    return ", ".join(w for w, _ in words.most_common(3)) or "misc"
