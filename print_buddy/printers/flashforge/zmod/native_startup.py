"""Native AD5X startup contract shared by finalization and preflight.

ZMod FAQ prescribes M190 S<bed>, M104 S<hotend> T0 before start
for single_extruder_multi_material. T0 here addresses the one heater,
not the first logical filament; subsequent T1 selection is preserved.
"""
import re

NUM = r'(?:\d+(?:\.\d*)?|\.\d+)'


def commands(text):
    # One partition per line; slicer files are mostly comments and run to 1M+ lines.
    out = []
    append = out.append
    for line in text.splitlines():
        line = line.partition(';')[0].strip()
        if line:
            append(line)
    return out


def _heater_run_consistent(cmd, bed, hotend):
    """Check immediate declarations without accepting later layer heaters."""
    for line in cmd:
        if not re.match(r'M(?:104|109|140|190)\b', line):
            break
        match = re.fullmatch(r'M(104|109|140|190) S(' + NUM + r')(?: T(\d+))?', line)
        if not match:
            return False
        target = bed if match.group(1) in ('140', '190') else hotend
        if float(match.group(2)) != float(target) or match.group(3) not in (None, '0'):
            return False
    return True


def _benign_preamble(cmd):
    """Only the observed Orca progress and fan-off declarations may precede startup.

    No generic M-code skipping: extra parameters, tool selections, motion,
    extrusion, heater commands and nonzero fan speeds remain forbidden.
    """
    return all(re.fullmatch(r'M73 P0 R\d+|M106 S0|M106 P2 S0', line)
               for line in cmd)


def valid(text, bed, hotend):
    cmd = commands(text)
    if len(cmd) < 3:
        return False
    starts = [i for i, line in enumerate(cmd) if line.startswith('START_PRINT ')]
    if len(starts) != 1:
        return False
    start = starts[0]
    # Allow only the observed benign slicer preamble BEFORE the contiguous
    # header. It cannot split a heater pair from START_PRINT.
    if start >= 2 and cmd[start - 2].startswith('M190 ') and _benign_preamble(cmd[:start - 2]):
        heater_cmd = cmd[start - 2:start]
    elif _benign_preamble(cmd[:start]):
        heater_cmd = cmd[start + 1:start + 3]
    else:
        return False
    if len(heater_cmd) != 2:
        return False
    expected = [('M190', float(bed), None), ('M104', float(hotend), 0)]
    for line, (code, temp, tool) in zip(heater_cmd, expected):
        pattern = code + r' S(' + NUM + r')' + (r' T0' if tool == 0 else '')
        match = re.fullmatch(pattern, line)
        if not match or float(match.group(1)) != temp:
            return False
    for key, target in [('BED_TEMP', bed), ('EXTRUDER_TEMP', hotend)]:
        values = re.findall(r'\b' + key + r'=(' + NUM + r')(?=\s|$)', cmd[start])
        if len(values) != 1 or float(values[0]) != float(target):
            return False
    # A valid leading pair must never mask conflicting post-start declarations.
    return _heater_run_consistent(cmd[start + 1:], bed, hotend)


def normalize(text):
    """Insert missing heaters adjacent to START_PRINT after a strict preamble."""
    cmd = commands(text)
    starts = [i for i, line in enumerate(cmd) if line.startswith('START_PRINT ')]
    if not starts:
        return text
    if len(starts) != 1:
        raise RuntimeError('native startup requires exactly one START_PRINT')
    start = starts[0]
    temps = []
    for key in ('BED_TEMP', 'EXTRUDER_TEMP'):
        values = re.findall(r'\b' + key + r'=(' + NUM + r')(?=\s|$)', cmd[start])
        if len(values) != 1 or float(values[0]) <= 0:
            raise RuntimeError('native startup missing or conflicting ' + key)
        temps.append(values[0])
    if not _heater_run_consistent(cmd, *temps) or not _heater_run_consistent(cmd[start + 1:], *temps):
        raise RuntimeError('conflicting or ambiguous native startup heater command')
    if valid(text, *temps):
        return text
    # Never bless a misplaced/partial existing header by adding another pair.
    if not _benign_preamble(cmd[:start]) or (len(cmd) > start + 1 and re.match(r'M(?:104|109|140|190)\b', cmd[start + 1])):
        raise RuntimeError('native startup requires contiguous recognized header order')
    lines = text.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines)
                 if line.split(';', 1)[0].strip().startswith('START_PRINT '))
    lines[index:index] = [f'M190 S{temps[0]}\n', f'M104 S{temps[1]} T0\n']
    result = ''.join(lines)
    if not valid(result, *temps):
        raise RuntimeError('native startup normalization failed')
    return result
