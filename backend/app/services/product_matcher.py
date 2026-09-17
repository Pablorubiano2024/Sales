"""Product matching utilities.

Matches a candidate product name (e.g. found at a supplier/source) against
canonical Products already in the catalog. This is a simple, deterministic
token-overlap similarity for the MVP — it is intentionally NOT a machine
learning / embeddings-based matcher. It exists so the discovery job has a
concrete way to decide "is this the same product" and can be swapped for a
smarter implementation later without touching callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models.product import Product

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def similarity(name_a: str, name_b: str) -> float:
    """Jaccard similarity between the token sets of two product names.
    Returns a value in [0, 1]; 0 when either name is empty."""
    tokens_a = _tokenize(name_a)
    tokens_b = _tokenize(name_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product: Product
    score: float


def find_best_match(
    candidate_name: str,
    catalog: list[Product],
    min_score: float = 0.4,
) -> ProductMatch | None:
    """Return the best-matching catalog Product for a candidate name, or
    None if nothing clears `min_score`."""
    best: ProductMatch | None = None
    for product in catalog:
        score = similarity(candidate_name, product.name)
        if best is None or score > best.score:
            best = ProductMatch(product=product, score=score)

    if best is not None and best.score >= min_score:
        return best
    return None
