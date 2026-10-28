"""Opt-in semantic layer behind the local fuzzy matcher (#468 stage 4).

Typos and synonyms are different failure classes. The local matcher
(``core.fuzzy``) handles character-level near-misses deterministically;
it cannot know that "bed won't stick" means "bed adhesion". Stage 4 lets
an operator point Print Handy at a semantic-search endpoint — the
reference shape is a small Cloudflare Worker over an embeddings model,
but anything answering the contract below works — and have *meaning*
matches offered when, and only when, the local matcher found nothing.

The posture is the #468 amendment's, and it is strict:

- **Opt-in and off by default.** ``PRINT_FUZZY_URL`` is a plain
  environment variable (no ``PRINT_HANDY__`` config form), read at call
  time. Unset, this module is never consulted and lookup is byte-identical
  to the local-only behaviour.
- **Stateless.** Only the query text and the caller's candidate list
  (public registry entries: id + display text) are sent. Nothing is
  stored, here or — per the contract the endpoint is asked to honour —
  there. Print numbers, spool IDs and per-install data (print history
  titles in particular) are never candidates.
- **Behind the local matcher.** Local exact/substring/fuzzy results are
  computed first and are never merged with or re-ranked by this layer;
  callers consult it only on a local no-match, and its hits are presented
  as suggestions, labelled as coming from the endpoint.
- **Silent degradation.** Any failure — unreachable, timeout, HTTP error,
  malformed body, or the endpoint answering ``degraded: true`` — returns
  ``[]`` and the local behaviour stands. The error is logged, the lookup
  is not.
- **No Authorization header.** The endpoint URL carries its secret in
  the path, the same posture as ``PRINT_VISION_URL``.

Contract (from the #468 spike, repo ``cf-fuzzy-search``): request
``POST {query, candidates: [{id, text}], threshold?, limit?}``; response
``{matches: [{id, text, score}], degraded: false}`` or
``{matches: [], degraded: true, reason}``. Scores are cosine similarities
in 0..1. ``DEFAULT_THRESHOLD`` is the spike's 0.55 — a placeholder chosen
before any live corpus existed, to be tuned against real lookups; it is
sent explicitly so the behaviour an install gets is the one documented
here, not whatever an endpoint defaults to.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
DEFAULT_THRESHOLD = 0.55
MAX_CANDIDATES = 1000
MAX_CANDIDATE_CHARS = 200


def configured() -> bool:
    """True when an operator has set PRINT_FUZZY_URL — the layer's only switch."""
    return bool(os.environ.get("PRINT_FUZZY_URL"))


def semantic_matches(query, candidates, *, limit=5):
    """Meaning-level matches for ``query`` from the configured endpoint, or [].

    ``candidates`` is a list of ``{"id", "text"}`` dicts. Returns a list of
    ``{"id", "text", "score"}`` dicts in the endpoint's order (score is the
    raw cosine similarity, 0..1), capped at ``limit``. Returns [] when
    PRINT_FUZZY_URL is unset or on any failure — callers treat [] as "the
    local answer stands".
    """
    url = os.environ.get("PRINT_FUZZY_URL")
    query = str(query or "").strip()
    if not url or not query or not candidates:
        return []
    payload = json.dumps({
        "query": query[:MAX_CANDIDATE_CHARS],
        "candidates": [{"id": str(c["id"]), "text": str(c["text"])[:MAX_CANDIDATE_CHARS]}
                       for c in candidates[:MAX_CANDIDATES]],
        "threshold": DEFAULT_THRESHOLD,
        "limit": limit,
    }).encode()
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("semantic lookup via PRINT_FUZZY_URL failed, keeping the local result: %s: %s",
                       type(exc).__name__, exc)
        return []
    if not isinstance(data, dict) or data.get("degraded"):
        if isinstance(data, dict) and data.get("degraded"):
            logger.warning("semantic lookup endpoint reports degraded: %s", data.get("reason") or "no reason given")
        return []
    matches = []
    for entry in data.get("matches") or []:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        try:
            score = float(entry.get("score", 0))
        except (TypeError, ValueError):
            continue
        matches.append({"id": str(entry["id"]), "text": str(entry.get("text", "")), "score": score})
    return matches[:limit]
