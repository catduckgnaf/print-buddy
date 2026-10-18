"""Quantity choices and strict parsing for a pending print quantity prompt."""
import re


def quantity_options(max_copies: int) -> list[tuple[str, int]]:
    """1, 2 and Max with real values. Word labels: Discord already prefixes buttons with "N. "."""
    maximum = max(1, int(max_copies))
    options = [('One copy', 1)]
    if maximum >= 2:
        options.append(('Two copies', 2))
    if maximum > 2:
        options.append((f'Max ({maximum} copies)', maximum))
    return options


def parse_quantity(text: str, maximum: int) -> int:
    """Accept only a single explicit integer, optionally phrased as a quantity."""
    value = str(text or '').strip().casefold()
    match = re.fullmatch(r'(?:print\s+)?(\d+)(?:\s*(?:copies|copy|prints?))?', value)
    if not match:
        raise ValueError(f'Reply with one number from 1 to {maximum}, or tap a button.')
    quantity = int(match.group(1))
    if not 1 <= quantity <= maximum:
        raise ValueError(f'{quantity} will not fit. This plate holds 1 to {maximum} copies.')
    return quantity
