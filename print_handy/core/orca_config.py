"""Read OrcaSlicer's per-filament config values from G-code headers."""


def split_config_list(value):
    """Split an Orca vector setting such as `PLA;"Silk PLA";PETG` into its items.

    Orca quotes an item that contains a space, a semicolon or a quote, and escapes
    `"` and `\\` inside quotes (`; filament_type = "Silk PLA";PLA`). Splitting on
    `;` alone keeps the quotes, which rejected every material name with a space
    (2026-10-30: a Silk PLA spool failed as "malformed per-tool filament_type").
    Items keep their position; an empty item stays an empty string.
    """
    if value is None:
        return []
    items, current, quoted, escaped, was_quoted = [], [], False, False, False
    for char in str(value).strip():
        if escaped:
            current.append(char)
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
            was_quoted = True
        elif char == ";" and not quoted:
            items.append("".join(current) if was_quoted else "".join(current).strip())
            current, was_quoted = [], False
        else:
            current.append(char)
    if quoted or escaped:
        raise ValueError("unterminated quoted value in slicer config list")
    items.append("".join(current) if was_quoted else "".join(current).strip())
    return items
