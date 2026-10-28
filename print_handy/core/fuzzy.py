"""Typo-tolerant similarity scoring (#468): deterministic, stdlib-only, offline.

One scorer shared by every fuzzy surface — knowledge lookup (stage 1),
print-history matching (stage 2) and did-you-mean command suggestions
(stage 3) — so the bands mean the same thing everywhere:

- ``score >= HIGH_CONFIDENCE`` (85): a high-confidence near-match.
- ``FUZZY_FLOOR <= score < HIGH_CONFIDENCE`` (65–84): suggestion material —
  fit for a "Did you mean …?" or a pick-list, never for acting on.
- ``score < FUZZY_FLOOR``: not a match; the function returns 0.

The score is the ``difflib.SequenceMatcher`` ratio of the whole normalized
strings, measured on the real registries in the #468 Stage 0 report
(~0.08 ms per comparison, the whole set in <6 ms, no dependency). Token-pair
averaging was measured too and rejected: it crowns false friends
("weather" → heater entries at 0.77, "fan" → anything containing "and" at
0.67) that the whole-string ratio keeps below the floor.

One guard rides on top of the ratio: token coverage. A multi-word query
whose words mostly match nothing in the target is a false friend even when
one long shared word inflates the ratio — "warp drive calibration" scored
0.65+ against "probe calibrate" on the strength of "calibration" alone.
So at least half of the query's words must each have a plausible partner
(ratio >= 0.65) among the target's words, or the score is 0. A typo'd word
still counts as covered when its partner is the word it mistyped
("adheison" → "adhesion", 0.88), so real multi-word typos pass.

A fuzzy score never reaches 100: exact is a separate tier owned by each
caller, deterministic exact matches always beat fuzzy ones, and a fuzzy
match by itself never runs anything — callers present it for a pick or a
confirmation that names the resolved target.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

FUZZY_FLOOR = 65
HIGH_CONFIDENCE = 85


def norm(text):
    """The folding every matcher in the repo already uses: lowercase, punctuation to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()


def _covered(query_tokens, target_tokens) -> bool:
    """True when at least half the query's words have a plausible partner word in the target."""
    if not query_tokens or not target_tokens:
        return False
    covered = sum(1 for word in query_tokens
                  if max(SequenceMatcher(None, word, other).ratio()
                         for other in target_tokens) * 100 >= FUZZY_FLOOR)
    return covered * 2 >= len(query_tokens)


def fuzzy_score(query, target) -> int:
    """Similarity of one query to one target name/alias, 0 or 65–99.

    Both sides are normalized first, so callers may pass raw or folded text.
    Returns 0 when either side is empty, the ratio falls below
    ``FUZZY_FLOOR`` — below the floor is "not a match", not a low score —
    or the token-coverage guard rejects the pair as a false friend.
    """
    q, t = norm(query), norm(target)
    if not q or not t:
        return 0
    score = round(SequenceMatcher(None, q, t).ratio() * 100)
    if score < FUZZY_FLOOR or not _covered(q.split(), t.split()):
        return 0
    return min(score, 99)


def best_fuzzy_score(query, targets) -> int:
    """The best ``fuzzy_score`` of a query over a candidate's names/aliases/ids."""
    return max((fuzzy_score(query, target) for target in targets), default=0)


def windowed_fuzzy_score(query, target) -> int:
    """Best ``fuzzy_score`` of a query against a target or a word window of it.

    For long candidate names where the query names only part of the name —
    print titles are the case in point: "desk stadn" scores 52 against the
    whole of "G4 Instant Desk Stand" but 90 against its "desk stand"
    window. Windows run one word shorter and one word longer than the query
    too, so a missing or extra space ("deskstand") still finds its window.
    The token-coverage guard applies inside every window: a window must
    still hold partners for at least half the query's words.
    """
    q, t = norm(query), norm(target)
    if not q or not t:
        return 0
    best = fuzzy_score(q, t)
    qtokens, ttokens = q.split(), t.split()
    if len(ttokens) > 1:
        for size in {len(qtokens) - 1, len(qtokens), len(qtokens) + 1}:
            if size < 1 or size >= len(ttokens):
                continue
            for start in range(len(ttokens) - size + 1):
                best = max(best, fuzzy_score(q, " ".join(ttokens[start:start + size])))
    return best
