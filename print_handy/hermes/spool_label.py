"""Photo/OCR spool intake: read a spool label photo into a spool spec (#514).

The conversational new-spool walkthrough (#512) can start from a photo of
the spool's box or manufacturer sticker instead of button picks. The photo
goes to the configured vision endpoint through the shared vision call
(visual_watch.visual_extract: image bytes + a JSON-only prompt); this
module owns the prompt and the validation of the answer.

``extract_spool_spec`` is pure and offline-testable: image bytes plus an
injected vision call in, a validated spec dict out — or a SpoolLabelError
naming why the photo could not be used (unreadable, non-JSON answer, or a
required field missing). The walkthrough refuses with that message and
falls back to the manual steps; nothing is ever created from a photo
without the operator confirming the extracted values first.

Label temperatures are data, not authority: they ride the spec as
``nozzle_temp`` / ``bed_temp`` and are recorded on the Spoolman filament
the spool is created with (spool_sync.create_spool), so the existing
temperature precedence holds for every material — a temperature recorded
on the filament wins over material defaults, and the #512 material
variant adjustments never override recorded data. No material is
special-cased here.

Nothing here stores or forwards the image anywhere: the one vision call
is the only place the bytes go.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

LABEL_PROMPT = (
    "You are reading a photo of a 3D printer filament spool's box or manufacturer label. "
    "Reply with a single JSON object and nothing else, with these keys: "
    '"brand" (the maker\'s name, or null), '
    '"material" (the filament material including any sub-type, e.g. "PLA", "Silk PLA", "PLA+", "PETG"), '
    '"color" (the colour name or multi-colour blend exactly as labelled), '
    '"grams" (the net filament weight in grams as a number), '
    '"nozzle_temp" (the recommended nozzle temperature in °C as a number, or null when not printed), '
    '"bed_temp" (the recommended bed temperature in °C as a number, or null when not printed). '
    "Do not guess: use null for anything the label does not print, and never invent a weight. "
    'If the photo does not show a readable filament label at all, reply {"unreadable": true}.'
)

# The named extraction failures (#514): each carries the plain-language
# message the walkthrough shows before falling back to the manual steps.
FAILURE_MESSAGES = {
    "unreadable": ("I couldn't read that label photo. Try a closer, well-lit shot of the "
                   "spool's box or sticker — or just pick the details by hand below."),
    "non_json": ("The vision answer for that photo wasn't usable, so nothing was read from it. "
                 "You can send another photo, or pick the details by hand below."),
    "missing_fields": ("That label photo didn't show everything a new spool needs ({missing}). "
                       "You can send a clearer photo, or pick the details by hand below."),
}


class SpoolLabelError(Exception):
    """A named label-extraction failure; ``reason`` is one of FAILURE_MESSAGES' keys."""

    def __init__(self, reason: str, missing: tuple[str, ...] = ()):
        self.reason = reason
        self.missing = missing
        message = FAILURE_MESSAGES[reason]
        if missing:
            message = message.format(missing=", ".join(missing))
        super().__init__(message)


def _strip_fence(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    return raw.strip()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:100]


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]


def _grams(value: Any) -> float | None:
    """Net weight in grams from a number, or a string like '1000', '1000 g', '1 kg'."""
    numbers = _numbers(value)
    if not numbers:
        return None
    grams = numbers[0]
    if isinstance(value, str) and re.search(r"\bkg\b", value, re.I) and grams < 50:
        grams *= 1000
    return round(grams, 1) if grams > 0 else None


def _temp(value: Any, low: float, high: float) -> float | None:
    """One temperature in °C; a printed range ('215-230') reads as its midpoint.

    Out-of-range values are dropped, not refused: the temperatures are
    optional label data, and a misread digit must not sink the whole spec.
    """
    numbers = _numbers(value)
    if not numbers:
        return None
    temp = (numbers[0] + numbers[1]) / 2 if len(numbers) > 1 else numbers[0]
    temp = round(temp, 1)
    return temp if low <= temp <= high else None


def extract_spool_spec(image: bytes, vision_call: Callable[[bytes, str], Any]) -> dict[str, Any]:
    """Read one spool label photo into a validated spec dict.

    ``vision_call`` is the shared vision call (visual_watch.visual_extract's
    shape): image bytes + prompt, returning the endpoint's parsed JSON, a
    raw string answer, or None when the call could not be completed. The
    returned spec is {brand, material, color, grams, nozzle_temp, bed_temp}
    with brand and the temperatures None when the label does not print
    them. Raises SpoolLabelError with a named reason when the photo cannot
    be used; the caller refuses with its message and falls back to the
    manual walkthrough.
    """
    if not image:
        raise SpoolLabelError("unreadable")
    try:
        answer = vision_call(image, LABEL_PROMPT)
    except Exception:
        raise SpoolLabelError("unreadable") from None
    if answer is None:
        raise SpoolLabelError("unreadable")
    if isinstance(answer, str):
        try:
            answer = json.loads(_strip_fence(answer))
        except ValueError:
            raise SpoolLabelError("non_json") from None
    if not isinstance(answer, dict):
        raise SpoolLabelError("non_json")
    if answer.get("unreadable"):
        raise SpoolLabelError("unreadable")
    material = _clean_text(answer.get("material"))
    color = _clean_text(answer.get("color"))
    grams = _grams(answer.get("grams"))
    missing = tuple(name for name, value in
                    (("material", material), ("colour", color), ("weight", grams)) if not value)
    if missing:
        raise SpoolLabelError("missing_fields", missing)
    brand = _clean_text(answer.get("brand")) or None
    return {"brand": brand, "material": material, "color": color, "grams": grams,
            "nozzle_temp": _temp(answer.get("nozzle_temp"), 80, 350),
            "bed_temp": _temp(answer.get("bed_temp"), 0, 150)}
