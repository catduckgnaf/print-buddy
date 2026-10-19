"""Source-first Discord intake. Downloads, records choices, then one button slices and optionally prints.

Printing starts only from a button click that confirms the bed is clear. No typed approval is required."""
import asyncio
import contextvars
import hashlib
import json
import re
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from .. import settings
from . import _external, split_fit

BED = settings.current()['printer']['bed_mm']
IFS_SLOTS = settings.current()['printer']['ifs_slots']
print_summary = _external.lazy('discord_print_summary')
print_next = _external.lazy('print_next')
from .link_intake import ask, model_link, has_duration_question  # noqa: E402
from .quantity_selection import quantity_options, parse_quantity  # noqa: E402


_OFFLOAD = {('model_job', 'audit'), ('model_job', 'slice_job'), ('source_colors', 'inventory'),
            ('orca_adapter', 'orca_plate_capacity'), ('orca_adapter', 'fit_options'),
            ('model_job', 'per_part_fit_options'), ('plate_merge', 'full_size_split_possible')}


async def _heavy(func, *args, **kwargs):
    """Run CPU-heavy intake work in a child process (own GIL) so Discord buttons answer in time.

    Threads are not enough: large 3MF XML parsing holds the GIL for ~10 s stretches and starves the
    gateway loop past Discord's 3 s interaction deadline. Substituted callables (tests) run in a thread.
    """
    import importlib
    mod, name = getattr(func, '__module__', None), getattr(func, '__name__', None)
    short = (mod or '').rsplit('.', 1)[-1]
    real = (short, name) in _OFFLOAD and getattr(importlib.import_module(mod), name, None) is func
    if not real:
        return await asyncio.to_thread(func, *args, **kwargs)
    def plain(v):
        return str(v) if isinstance(v, Path) else v
    payload = json.dumps({'module': short, 'func': name, 'args': [plain(a) for a in args],
                          'kwargs': {k: plain(v) for k, v in kwargs.items()}}).encode()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'print_buddy.core.heavy_worker', cwd=str(settings.ROOT),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(payload)
    try:
        reply = json.loads(out.decode().rstrip().rsplit('\n', 1)[-1])
    except (ValueError, IndexError):
        raise RuntimeError(f'{name} worker failed: {err.decode(errors="replace")[-400:]}') from None
    if not reply.get('ok'):
        exc = {'ValueError': ValueError, 'FileNotFoundError': FileNotFoundError}.get(reply.get('type'), RuntimeError)
        raise exc(reply.get('error'))
    return Path(reply['result']) if reply.get('path') else reply['result']


def write_split_plan(job_path, job, manifest, gcodes, plan_id, plans_dir=None):
    """Record a split slice as a multipart plan that /print-next can resolve exactly.

    Each plate gets one required part bound to its archived JOB.json and absolute
    G-code path. The plan id is also stored in JOB.json so record_start can put
    it in the print context and completions advance the plan.
    """
    print_records = _external.load('print_records')
    names = {p['key']: re.sub(r'\.(stl|3mf)$', '', p['name'], flags=re.I) for p in manifest['parts']}
    rows = {str(Path(r['gcode']).resolve()): r for r in job.get('derived_plates') or [] if r.get('gcode')}
    parts = []
    for n, g in enumerate(gcodes, 1):
        row = rows.get(str(Path(g).resolve()), {})
        label = ', '.join(names.get(k, k) for k in row.get('part_keys') or []) or Path(g).stem
        if row.get('slot') is not None:
            label += f" (slot {row['slot']})"
        parts.append({'id': f'plate{n}', 'label': label, 'plate': n, 'quantity': 1, 'completed_quantity': 0,
                      'status': 'planned', 'gcode_file': Path(g).name, 'job_json': str(Path(job_path).resolve()),
                      'gcode_path': str(Path(g).resolve())})
    merge = job.get('plate_merge') or {}
    reason = merge.get('reason') or ('the chosen slots were sliced as separate single-color plates'
                                     if not merge else 'the merge planner could not place them on one bed')
    plan = {'plan_id': plan_id, 'title': job.get('title'), 'split_reason': reason, 'parts': parts}
    target = (plans_dir or print_records.PLANS_DIR) / f'{plan_id}.json'
    print_records._atomic_write(target, json.dumps(plan, indent=2) + '\n')
    latest = json.loads(Path(job_path).read_text())
    latest['multipart_plan'] = {'plan_id': plan_id, 'split_reason': reason, 'parts': parts}
    Path(job_path).write_text(json.dumps(latest, indent=2) + '\n')
    return plan


def _preview_description(text):
    """Brief source-derived description: first sentence, no URLs, paths, filenames or hashes."""
    text = re.sub(r'https?://\S+', ' ', str(text or ''))
    words = [w for w in text.split()
             if '/' not in w and '\\' not in w and not re.search(r'\.(?:3mf|stl|gcode|step|obj|zip)\b', w, re.I)
             and not re.fullmatch(r'[0-9a-fA-F]{16,}', w)]
    text = ' '.join(words).strip()
    first = re.split(r'(?<=[.!?])\s', text, maxsplit=1)[0].strip().rstrip('.!?:;,- ')
    if len(first) > 120:
        first = first[:120].rsplit(' ', 1)[0].rstrip('.,;:- ')
    return first


def _preview_estimate(row):
    """(seconds, grams) only from a source estimate explicitly for the AD5X; else None. Never guessed."""
    printer = re.sub(r'[^a-z0-9]', '', str((row or {}).get('site_printer') or '').lower())
    plates = (row or {}).get('plates')
    if not ('ad5x' in printer or 'adventurer5x' in printer) or not isinstance(plates, list) or not plates:
        return None
    seconds = grams = 0.0
    for plate in plates:
        if not isinstance(plate, dict):
            return None
        s, g = plate.get('prediction_s'), plate.get('weight_g')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v < 1e7 for v in (s, g)):
            return None
        seconds += float(s)
        grams += float(g)
    return seconds, grams


def _preview_profile(row):
    """The exact profile the intake will download, in a Discord-safe sentence fragment."""
    row = row or {}
    label = str(row.get('title') or row.get('name') or '').strip()
    label = re.sub(r'\s+', ' ', label)
    # A bare source filename is still the profile name; drop only its model extension.
    label = re.sub(r'\.(?:3mf|stl|step|stp|obj|gcode|zip)$', '', label, flags=re.I).strip()
    if not row.get('title') and re.fullmatch(r'(?:model|print|file)?[_-]?[0-9a-f]{6,}', label, re.I):
        return ''
    return _preview_description(label)


def preview_sentence(job, row):
    title = re.sub(r'\s+', ' ', str((job or {}).get('title') or '')).strip()
    if not title:
        return None
    desc = _preview_description((job or {}).get('summary'))
    profile = _preview_profile(row)
    est = _preview_estimate(row)
    named_profile = bool(profile and str((row or {}).get('title') or '').strip())
    if not desc and not est and not named_profile:
        return None  # a bare title or filename echo adds nothing; a named profile does
    text = f'That looks like {title}' + (f', {desc}' if desc else '') + '.'
    if profile and profile.casefold() != title.casefold():
        text += f' I will use the selected profile: {profile}.'
    if est:
        from . import model_job as mj
        text += (f' AD5X estimated print time about {mj.human_dur(est[0])}, plus ~5 min '
                 f'warmup ({mj.human_dur(est[0] + 300)} total), and {round(est[1])} g of filament before color selection.')
    else:
        from . import model_job as mj
        site = mj.source_site_estimate(row)
        if site:
            printer = str((row or {}).get('site_printer') or '').strip()
            plates = len((row or {}).get('plates') or [])
            text += (f" Model page estimate{f' (for {printer})' if printer else ''}: about {mj.human_dur(site[0])}"
                     f" and {round(site[1])} g of filament{f' over {plates} plates' if plates > 1 else ''}."
                     ' The AD5X figure after slicing will differ somewhat.')
        else:
            text += ' The model page gives no time or filament estimate; I will report both after slicing.'
    return text


async def send_preview(adapter, source, job, row, metadata):
    """Best effort, display only: no printer, Moonraker, Spoolman, HA or persistence I/O."""
    try:
        text = preview_sentence(job, row)
        if text:
            await adapter.send(chat_id=source.chat_id, content=text, metadata=metadata)
    except Exception:
        pass


def _pct(scale):
    return f'{round(scale * 100, 1):g}%'


def fit_choice_rows(options):
    """At most four short choices, with full-size split before orientation/shrink."""
    rows = []
    split_plan = options.get('split_plan')
    if split_plan:
        rows.append({'kind': 'split', 'label': f"100% · split {len(split_plan['plates'])} plates",
                     'plates': split_plan['plates'], 'scale': 1.0})
    elif options.get('full_size_split'):
        rows.append({'kind': 'split', 'label': 'Split plates at 100%', 'scale': 1.0})
    split_available = any(row['kind'] == 'split' for row in rows)
    for alt in (options.get('rotations') or [])[:1 if split_available else 2]:
        scale = float(alt['scale'])
        if scale < 0.995:
            continue
        support = ' + supports' if alt.get('supports') else ' · rotated'
        rows.append({'kind': 'rotate', 'label': f'{_pct(scale)}{support}', 'scale': scale,
                     'rotation': alt['rotation'], 'axis': alt.get('axis'),
                     'dims_full_mm': alt.get('dims_full_mm'), 'supports': bool(alt.get('supports')),
                     'brim': bool(alt.get('brim'))})
        if len(rows) == 2:
            break
    if len(rows) < 3:
        for scale in options.get('scales') or []:
            if float(scale) < 0.995:
                rows.append({'kind': 'scale', 'label': f'Shrink to {_pct(scale)}', 'scale': float(scale)})
                break
    rows.append({'kind': 'cancel', 'label': 'Cancel'})
    return rows


def _fit_choice_reply(text, rows):
    """Resolve typed fit intent only when it names one available action."""
    value = str(text or '').strip().casefold()
    if value in {'split', 'separate', 'split plates'}:
        matches = [i for i, row in enumerate(rows) if row['kind'] == 'split'
                   or (row['kind'] == 'painted' and 'split' in row['label'])]
    elif value in {'100%', '100', 'full', 'full size'} or 'full size' in value:
        matches = [i for i, row in enumerate(rows) if row['kind'] == 'split'
                   or (row['kind'] == 'painted' and row['scale'] >= 1.0)]
    elif value in {'cancel', 'stop', "don't print"}:
        matches = [i for i, row in enumerate(rows) if row['kind'] == 'cancel']
    elif value in {'shrink', 'smaller'}:
        matches = [i for i, row in enumerate(rows) if row['kind'] == 'scale'
                   or (row['kind'] == 'painted' and row['scale'] < 1.0)]
    elif re.fullmatch(r'\d+(?:\.\d+)?\s*%', value):
        percent = float(value.rstrip('%').strip())
        matches = [i for i, row in enumerate(rows)
                   if row['kind'] in ('scale', 'rotate', 'painted') and abs(row['scale'] * 100 - percent) < 0.06]
    elif re.fullmatch(r'\d+(?:\.\d+)?', value):
        percent = float(value)
        matches = [i for i, row in enumerate(rows)
                   if row['kind'] in ('scale', 'rotate', 'painted') and abs(row['scale'] * 100 - percent) < 0.06]
    else:
        return None
    if len(matches) != 1:
        raise ValueError('that fit choice is not available; choose a listed button')
    return matches[0]


def fit_question(title, options):
    scales = options.get('scales') or []
    rotations = options.get('rotations') or []
    lines = [f'{title} does not fit the AD5X bed full size as authored.']
    if scales:
        lines.append(f'As authored it fits at {_pct(scales[0])} max.')
    for alt in rotations[:2]:
        size = ' x '.join(f'{v:g}' for v in alt.get('dims_mm') or [])
        warn = []
        if alt.get('supports'):
            warn.append('needs supports (overhangs face down; expect support marks)')
        if alt.get('brim'):
            warn.append('small bed contact for its height, so a 5 mm brim is added')
        lines.append(f"Rotated: {alt['label'].split(',')[0]} fits at "
                     f"{'full size' if alt['scale'] >= 1 else _pct(alt['scale'])} ({size} mm)"
                     + (f"; {'; '.join(warn)}" if warn else '') + '.')
    if options.get('full_size_split'):
        lines.append('Full-size option: split onto the original plates (100%).')
    lines.append('Pick a fit option, or type split / 100% / shrink / cancel.')
    return '\n'.join(lines)


def _fit_failure(job, capacity):
    model = str(job.get('title') or 'The selected model')
    source = job.get('selected_source') or {}
    if isinstance(source, dict):
        plate = str(source.get('title') or source.get('name') or 'selected source')
    else:
        plate = str(source or 'selected source')
    return (f'{model} using {plate} does not fit on one AD5X plate: calculated capacity is {capacity} copy with '
            '10 mm spacing and 8 mm edge margins. Choose a smaller profile, split it into plates, or scale it down.')


MODEL_FILE_EXTS = {'.3mf', '.stl'}


def model_file(event):
    """The single .3mf/.stl dropped in Discord (gateway cache path), else None. A link always wins."""
    hits = [Path(p) for p in (getattr(event, 'media_urls', None) or [])
            if Path(str(p)).suffix.lower() in MODEL_FILE_EXTS]
    return hits[0] if len(hits) == 1 and hits[0].is_file() else None


def upload_job(path):
    """Local job for a file the operator downloaded themselves; same shape as a one-profile site inventory."""
    name = re.sub(r'^doc_[0-9a-f]{12}_', '', Path(path).name)
    stem = Path(name).stem
    return {'site': 'upload', 'model_id': stem, 'title': stem, 'slug': stem, 'license': None, 'summary': '',
            'sources': [{'n': 1, 'name': name, 'title': stem, 'path': str(path)}]}


def upload_title(path, limit=1 << 20):
    """The designer's Title from a dropped 3MF, so uploads read like links ("Slim 12oz Can Holder..."
    rather than "CanHolder3MF"). Reads only the head of 3D/3dmodel.model; None when absent or not a 3MF."""
    import html
    import zipfile
    try:
        with zipfile.ZipFile(path) as z, z.open('3D/3dmodel.model') as f:
            head = f.read(limit).decode('utf-8', 'ignore')
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    m = re.search(r'<metadata\s+name="Title"[^>]*>([^<]*)</metadata>', head)
    title = html.unescape(m[1]).strip() if m else ''
    return title[:120] or None


def copy_upload(job, source, target):
    import shutil
    target.mkdir(parents=True, exist_ok=True)
    dest = target / source['name']
    shutil.copy2(source['path'], dest)
    return dest


REPRINT_RE = re.compile(
    r"\b(?:re-?print|print (?:it|that|this|that one|this one) again"
    r"|(?:print|slice|make|do) (?:the |that )?(?:last|previous|same) (?:one|print|model|thing|job)"
    r"|(?:print|slice|make|do) (?:the )?(?:last|previous) one|(?:print|make) (?:another|one more))\b", re.I)


def reprint_request(text):
    """'print the previous print in black', 'reprint that', 'print it again'. Never when a link is present."""
    text = str(text or '')
    return 'http' not in text.lower() and bool(REPRINT_RE.search(text))


def last_job(archive=None):
    """Newest archived job whose source file is still on disk, else None. Local files only."""
    from . import model_job as mj
    best = None
    for jp in Path(archive or mj.ARCHIVE).glob('*/JOB.json'):
        try:
            job = json.loads(jp.read_text())
        except (OSError, ValueError):
            continue
        f = Path(job.get('downloaded_file') or '')
        if job.get('selected_source') and f.is_file() and f.stat().st_size > 0:
            when = jp.stat().st_mtime
            if best is None or when > best[0]:
                best = (when, job)
    return best[1] if best else None


def reuse_job(prev):
    """Fresh job built from an archived one: same model and profile, source copied from disk, no site I/O."""
    row = dict(prev['selected_source'], path=prev['downloaded_file'], name=Path(prev['downloaded_file']).name)
    keep = ('site', 'model_id', 'title', 'slug', 'license', 'summary')
    return dict({k: prev.get(k) for k in keep}, sources=[row], reused_from=prev.get('intake_id'))


_LIVE_KEY = contextvars.ContextVar('prepared_intake_live_key', default=None)


from .link_intake import PromptCancelled as IntakeCancelled  # noqa: E402  typed Cancel/Stop at any prompt


async def _spool_projection_text(mj, job, manifest, state, copies):
    """Display only: filament needed vs the chosen spool's grams. Never blocks the intake."""
    try:
        ids = [sel.get('spoolman_id') for sel, _ in mj.filament_usage_by_selection(job, manifest)]
        if not ids:
            return ''
        fetch = None
        base = (state or {}).get('spoolman_url')
        if base:
            from . import spool_lifecycle

            def fetch(sid):
                return spool_lifecycle.fetch_spoolman_spool(sid, base_url=base)
        weights = await _heavy(mj.intake_spool_weights, state, ids, fetch)
        rows = mj.intake_spool_projection(job, weights, manifest, copies=copies)
        return mj.format_spool_projection(rows)
    except Exception:
        return ''


async def _ask(adapter, source, key, question, choices, timeout=300, **kwargs):
    """ask() registered under the live chat session so typed replies reach the prompt."""
    live_key = kwargs.pop('live_key', None) or _LIVE_KEY.get() or key
    return await ask(adapter, source, key, question, list(choices), timeout, live_key=live_key, **kwargs)


async def _send_render_preview(adapter, source, path, scale=1.0, rotation=None, bed=tuple(BED)):
    from .render_preview import render
    image_path = await asyncio.to_thread(render, path, scale, rotation, bed)
    await adapter.send(chat_id=source.chat_id,
                       content='Oriented and scaled model preview (bed outline shown).\\nMEDIA:' + image_path,
                       metadata={'thread_id': source.thread_id} if source.thread_id else None)


async def _send_source_thumbnail(adapter, source, path, target):
    """Best effort display of a source-authored painted 3MF preview; never blocks intake."""
    import zipfile
    from PIL import Image

    preferred = ('Auxiliaries/.thumbnails/thumbnail_3mf.png',
                 'Metadata/plate_1.png', 'Metadata/thumbnail.png')

    def extract():
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                name = next((item for item in preferred if item in names), None)
                if name is None:
                    return None
                target_path = Path(target)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source_file, Image.open(source_file) as image:
                    image.load()
                    if image.width < 32 or image.height < 32:
                        return None
                    image.convert('RGB').save(target_path, format='PNG')
                return str(target_path)
        except (OSError, ValueError, zipfile.BadZipFile):
            return None

    try:
        image_path = await asyncio.to_thread(extract)
        if image_path:
            await adapter.send(chat_id=source.chat_id,
                               content='Source model preview (from the supplied 3MF).\\nMEDIA:' + image_path,
                               metadata={'thread_id': source.thread_id} if source.thread_id else None)
    except Exception:
        pass


async def prepare_link(event, adapter, state, root, timeout=300, reuse=None):
    from . import model_job as mj
    from .source_colors import inventory, canonical_prompts, grouped_prompts, validate_decisions
    source = event.source
    url = None if reuse else model_link(event.text)
    upload = None if (url or reuse) else model_file(event)
    mid = getattr(event, 'message_id', None)
    if not (url or upload or reuse) or not mid:
        raise ValueError('plain model link requires a stable Discord message ID')
    iid = mj.intake_id_from_message(source, mid)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    receipt_path = root / (iid + '.json')
    origin = (url or (f'reprint:{reuse.get("intake_id")}' if reuse else None)
              or f'upload:{upload_job(upload)["sources"][0]["name"]}')
    receipt = {'intake_id': iid, 'url': origin, 'status': 'INSPECTING_SOURCE',
               'sliced': False, 'uploaded': False, 'started': False}
    try:
        with receipt_path.open('x') as f:
            json.dump(receipt, f)
    except FileExistsError:
        return {'action': 'skip', 'reason': 'duplicate model-link event'}
    key = 'model-link:' + iid
    event_metadata = getattr(event, 'metadata', None) or {}
    live_token = _LIVE_KEY.set(event_metadata.get('live_session_key') or key)
    metadata = {'thread_id': source.thread_id} if source.thread_id else None
    try:
        if reuse:
            done = reuse.get('sliced_at') and (reuse.get('filament_selection') or {}).get('color')
            when = f" (last sliced in {reuse['filament_selection']['color']})" if done else ''
            pick = await _ask(adapter, source, key, f"Did you mean {reuse.get('title') or 'the last model'}{when}? "
                             'I will slice it again from the saved file, no download.',
                             ['Yes, slice it again', "No, I'll send a link"], timeout)
            if pick != 0:
                receipt.update(status='DECLINED_REPRINT')
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                await adapter.send(chat_id=source.chat_id, metadata=metadata,
                                   content='OK. Send the link or drop the file. Nothing was sliced or started.')
                return {'action': 'skip', 'reason': 'reprint declined'}
            job = reuse_job(reuse)
            url = reuse.get('url')
        elif upload:
            job = upload_job(upload)
        else:
            job = await asyncio.to_thread(mj.maker_inventory if 'makerworld.com' in urlsplit(url).hostname
                                          else mj.printables_inventory, url)
        rows = job.get('sources', [])
        if job['site'] == 'printables':
            rows = [r for r in rows if Path(r.get('name', '')).suffix.lower() in {'.3mf', '.stl'}]
        if not rows:
            raise ValueError('source inventory contains no selectable geometry')
        hint = re.fullmatch(r'profileId-(\d+)', urlsplit(url or '').fragment or '')
        suggested = [r for r in rows if hint and str(r.get('instance_id')) == hint[1]]
        if job['site'] == 'makerworld':
            from .makerworld_profiles import choose as choose_maker_profile, selection_summary
            chosen = choose_maker_profile(rows, hint[1] if hint else None)
            if chosen is not None:
                # The concise intake preview below carries model description and validated
                # AD5X estimates. Avoid repeating the long source-printer profile summary.
                pass
            else:
                labels = [f"{i}: {selection_summary(r)}"[:96] for i, r in enumerate(rows, 1)]
                labels.append('Do not print (Cancel)')
                selected = await _ask(adapter, source, key,
                    f"This model has {len(rows)} print profiles; choose the design/profile to inspect.", labels, timeout)
                if selected == len(rows):
                    raise IntakeCancelled
                chosen = rows[selected]
        elif len(rows) == 1:
            chosen = rows[0]
        elif len(rows) <= 4:
            labels = [f"{i}: {r.get('title') or r.get('name')}"[:70]
                      + (' (suggested by link)' if len(suggested) == 1 and r is suggested[0] else '')
                      for i, r in enumerate(rows, 1)]
            chosen = rows[await _ask(adapter, source, key,
                                     f'This model has {len(rows)} print profiles. Which profile should I use?',
                                     labels, timeout)]
        else:
            # More than four choices are never resolved from arbitrary typed text.
            # Present the available options only; the intake can be restarted with a narrower source.
            order = list(suggested[:1]) + [r for r in rows if not suggested[:1] or r is not suggested[0]]
            shown = order[:4]
            labels = [f"{rows.index(r) + 1}: {r.get('title') or r.get('name')}"[:70]
                      + (' (suggested by link)' if suggested[:1] and r is suggested[0] else '')
                      for r in shown]
            pick = await _ask(adapter, source, key,
                             f'This model has {len(rows)} print profiles. Showing {len(shown)}; '
                             'choose Other and type a profile number or name for any other.',
                             labels, timeout, allow_other=True)
            if isinstance(pick, int):
                chosen = shown[pick]
            else:
                typed = pick.strip().casefold()
                num = re.fullmatch(r'#?(\d+)(?::.*)?', typed)
                hits = [r for i, r in enumerate(rows, 1) if num and (str(i) == num[1] or str(r.get('instance_id')) == num[1])]
                if not hits:
                    hits = [r for r in rows if typed and typed in f"{r.get('title') or ''} {r.get('name') or ''}".casefold()]
                if len(hits) != 1:
                    raise ValueError(f'"{pick}" matched {len(hits)} of {len(rows)} profiles; send the link again and give a profile number or a more specific name')
                chosen = hits[0]
        await send_preview(adapter, source, job, chosen, metadata)
        folder = mj.intake_folder(mj.ARCHIVE, job['slug'], iid)
        folder.mkdir(parents=True, exist_ok=False)
        job.update(url=url, intake_id=iid, hardware=state, selected_source=chosen)
        fetch = copy_upload if (reuse or job['site'] == 'upload') else {'makerworld': mj.maker_download}.get(
            job['site'], mj.printables_download)
        path = await asyncio.to_thread(fetch, job, chosen, folder / 'source')
        job['downloaded_file'] = str(path)
        if job['site'] == 'upload':
            job['title'] = await asyncio.to_thread(upload_title, path) or job['title']
        job['audit'] = await _heavy(mj.audit, path)
        # Inspecting a large multi-object 3MF is ~30 s of pure-Python XML work. It must never run on the
        # gateway event loop (that froze Discord button callbacks). The audit already inspected these exact
        # bytes; reuse its manifest only if it is bound to the file's current SHA256, else inspect off-loop.
        manifest = (job['audit'] or {}).get('color_manifest') if isinstance(job['audit'], dict) else None
        actual_sha = await asyncio.to_thread(mj.file_sha256, path)
        if not (isinstance(manifest, dict) and manifest.get('source_sha256') == actual_sha):
            manifest = await _heavy(inventory, path)
        # STL has no source palette, but still needs an exact-source color decision.
        if not manifest.get('source_sha256'):
            manifest.update(source_sha256=await asyncio.to_thread(mj.file_sha256, path))
        job['color_manifest'] = manifest
        job['color_schema'] = 'part_slots_v1'
        jp = folder / 'JOB.json'
        mj.write_job(folder, job)
        receipt.update(job_json=str(jp), source_sha256=manifest['source_sha256'], status='AWAITING_COLOR')
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        selections = [mj.resolve_filament_selection(state, dict(label, slot=int(slot)))
                      for slot, label in sorted(state.get('ifs_slots', {}).items())]
        labels = mj.build_slot_labels(selections)
        if not labels or len(labels) > IFS_SLOTS or len(set(labels)) != len(labels):
            raise ValueError('requires one to four distinct configured slots')
        questions = canonical_prompts(manifest)
        grouped = grouped_prompts(manifest)
        families = [row for row in grouped if len(row['keys']) > 1]
        tally = {}
        for p in manifest['parts']:
            label = re.sub(r'\.(stl|3mf|obj|step|stp)$', '', p['name'], flags=re.I)
            tally[label] = tally.get(label, 0) + 1
        names = ', '.join(f'{n}× {k}' if n > 1 else k for k, n in tally.items()) or Path(path).name
        if questions and (len(manifest['parts']) > 1 or manifest['painted']):
            options = ['Keep distinct source regions' if manifest['painted'] else 'Choose colors for these parts',
                       'One color for everything']
            if families:
                together = '; '.join(row['question'].split(' for ', 1)[1].split(' (', 1)[0] for row in families)
                options[0] = f'Choose colors ({together} share one color)'[:80]
                options.append('Choose every part individually')
            count = len(manifest['parts'])
            found = f"Inspected {count} part{'s' if count != 1 else ''}: {names}."
            prompt = (f'{found} Keep distinct source regions or explicitly use one color for everything? '
                      'Keeping painted regions prints each painted area in the color you pick for it.'
                      if manifest['painted'] else
                      f'{found} Choose colors for these parts or one color for everything?')
            mode = await _ask(adapter, source, key, prompt, options, timeout)
        else:
            mode = 1
        decisions = {'source_sha256': manifest['source_sha256'], 'schema': 'part_slots_v1',
                     'mode': 'single_color' if mode == 1 else 'per_part'}
        if mode != 1:
            # Numbered siblings (Stencil 1/2/3) get one question unless the operator chose per part.
            rows = grouped if mode == 0 else [{**row, 'keys': [row['key']]} for row in questions]
            choices = {}
            for row in rows:
                picked = selections[await _ask(adapter, source, key, row['question'], labels, timeout)]
                for decision_key in row['keys']:
                    choices[decision_key] = picked
            decisions['choices'] = choices
        else:
            decisions['selection'] = selections[await _ask(adapter, source, key, f'Choose the color for {names}', labels, timeout)]
        latest = json.loads(jp.read_text())
        if (latest.get('intake_id') != iid or latest.get('color_decisions')
                or mj.file_sha256(latest['downloaded_file']) != decisions['source_sha256']):
            raise ValueError('source/job changed during selection; decisions not saved')
        validated = validate_decisions(manifest, decisions, state, mj.resolve_filament_selection)
        mj.set_color_decisions(latest, validated)
        if decisions['mode'] == 'single_color':
            latest['filament_selection'] = validated['selection']
        from . import orca_adapter
        try:
            capacity = await _heavy(orca_adapter.orca_plate_capacity, path, state)
        except Exception as exc:
            receipt['status'] = 'FIT_UNKNOWN'
            receipt['fit_error'] = str(exc)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            await adapter.send(chat_id=source.chat_id,
                               content=f"Fit check is unverified and can be resumed. No slice or print was started. {exc}",
                               metadata=metadata)
            return {'action': 'skip', 'reason': 'fit unknown; resumable'}
        painted_multi = (manifest.get('painted') and (latest.get('color_decisions') or {}).get('mode') == 'per_part')
        if capacity < 1 and painted_multi:
            # Painted multicolor: one multicolor G-code per authored plate at
            # one shared scale, 100% whenever it fits. No per-slot shrink rows.
            title = latest.get('title') or 'This model'
            try:
                fit = await _heavy(mj.painted_fit_for_job, path, latest['color_decisions'])
            except Exception as exc:
                fit = {'scale': None, 'error': str(exc)}
            receipt['painted_fit'] = fit
            scale = fit.get('scale')
            if scale is None:
                picked = [{'kind': 'cancel', 'label': 'Cancel'}]
                prompt = (f"{title} does not fit the AD5X bed with its prime tower at 50% or larger, "
                          'even split into its plates.')
            else:
                plates = fit['plates']
                where = f"{plates} plates" if plates > 1 else 'one plate'
                label = f"100% · split {plates} plates" if scale >= 1.0 and plates > 1 else f"{_pct(scale)} · {where}"
                picked = [{'kind': 'painted', 'label': label, 'scale': scale}, {'kind': 'cancel', 'label': 'Cancel'}]
                if scale >= 1.0:
                    prompt = f"{title} prints at 100% as {where}, each in all its painted colors."
                else:
                    prompt = (f"{title} is too big to print at 100% even split into its plates. The largest size "
                              f"that fits with the color-change tower is {_pct(scale)}, as {where}, every part at the "
                              'same size so they still fit together.')
            row = picked[await _ask(adapter, source, key, prompt, [r['label'] for r in picked], timeout,
                                    parser=lambda text: _fit_choice_reply(text, picked))]
            if row['kind'] == 'cancel':
                receipt['status'] = 'CANCELLED_OVERSIZED'
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                await adapter.send(chat_id=source.chat_id,
                                   content='Print cancelled. Nothing was sliced, uploaded, or started.',
                                   metadata=metadata)
                return {'action': 'skip', 'reason': 'cancelled oversized model'}
            latest['plate_mode'] = 'separate'
            latest['scale'] = row['scale']
            receipt['scale'] = row['scale']
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            mj.write_job(folder, latest)
            capacity = 1
        if capacity < 1:
            try:
                options = await _heavy(orca_adapter.fit_options, path, state)
            except Exception as exc:
                receipt['status'] = 'FIT_UNKNOWN'
                receipt['fit_error'] = str(exc)
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                await adapter.send(chat_id=source.chat_id,
                                   content=f"Resize checks are unverified and can be resumed. No slice or print was started. {exc}",
                                   metadata=metadata)
                return {'action': 'skip', 'reason': 'fit unknown; resumable'}
            title = latest.get('title') or 'This model'
            # Per-part slicing applies the chosen fit to every slot plate. Offer
            # only the options every slot plate was verified to honor.
            if (latest.get('color_decisions') or {}).get('mode') == 'per_part':
                options = await _heavy(mj.per_part_fit_options, path, latest['color_decisions'], options,
                                       int((state.get('bed_mm') or BED)[0]))
            full_size_split = False
            try:
                full_size_split = await _heavy(plate_merge.full_size_split_possible, path, manifest,
                                               int((state.get('bed_mm') or BED)[0]))
            except Exception:
                full_size_split = False
            try:
                split_plan = await _heavy(split_fit.split_plan_100, path,
                                          int((state.get('bed_mm') or BED)[0]))
            except Exception:
                split_plan = None
            if split_plan:
                options['split_plan'] = split_plan
            elif full_size_split:
                options['full_size_split'] = True
            picked = fit_choice_rows(options)
            fit_receipt = {'scales': options.get('scales') or [],
                           'rotations': [{k: r.get(k) for k in ('label', 'scale', 'axis', 'dims_mm',
                                                                'supports', 'brim')}
                                         for r in options.get('rotations') or []]}
            if split_plan:
                fit_receipt['split_plan'] = split_plan
            elif full_size_split:
                fit_receipt['full_size_split'] = True
            receipt['fit_options'] = fit_receipt
            if not any(r['kind'] in ('scale', 'rotate', 'split') for r in picked):  # nothing printable to offer
                if (latest.get('color_decisions') or {}).get('mode') == 'per_part':
                    message = (f"{title} only fits when resized, and none of the resize options work with "
                               'these per-part colors. Cancel, then resend the link and choose single color to resize it.')
                else:
                    message = f"{title} has no verified fit at 50% or larger in any orientation."
                await _ask(adapter, source, key, message, ['Do not print (Cancel)'], timeout)
                receipt['status'] = 'CANCELLED_OVERSIZED'
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                await adapter.send(chat_id=source.chat_id,
                                   content='Print cancelled. Nothing was sliced, uploaded, or started.',
                                   metadata=metadata)
                return {'action': 'skip', 'reason': 'cancelled oversized model'}
            split_plan = options.get('split_plan')
            if split_plan:
                distribution = []
                names_by_key = {part['key']: part['name'] for part in manifest.get('parts', [])}
                for index, part_keys in enumerate(split_plan['plates'], 1):
                    names = ', '.join(names_by_key.get(key, key) for key in part_keys)
                    distribution.append(f'{names} on plate {index}')
                prompt = (f"{title} does not fit the AD5X bed full size as one plate. "
                          f"Full size works as {len(split_plan['plates'])} plates: " + '; '.join(distribution) +
                          '. Choose a fit option, or type split / 100% / shrink / cancel.')
            else:
                prompt = fit_question(title, options)
            while True:
                scale_pick = await _ask(adapter, source, key, prompt,
                                        [row['label'] for row in picked], timeout,
                                        parser=lambda text: _fit_choice_reply(text, picked))
                row = picked[scale_pick]
                if row['kind'] != 'render':
                    break
                try:
                    await _send_render_preview(adapter, source, path,
                        row.get('scale', 1.0), row.get('rotation'),
                        tuple(state.get('bed_mm') or BED))
                except Exception as exc:
                    await adapter.send(chat_id=source.chat_id,
                        content=f'Preview unavailable: {exc}. No blank image was sent.', metadata=metadata)
            if row['kind'] == 'cancel':
                receipt['status'] = 'CANCELLED_OVERSIZED'
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                await adapter.send(chat_id=source.chat_id,
                                   content='Print cancelled. Nothing was sliced, uploaded, or started.',
                                   metadata=metadata)
                return {'action': 'skip', 'reason': 'cancelled oversized model'}
            if row['kind'] == 'split':
                latest['plate_mode'] = 'separate'
                latest['scale'] = 1.0
                if row.get('plates'):
                    latest['full_size_split_plan'] = {'plates': row['plates']}
                latest.pop('orientation', None)
                receipt['full_size_split'] = True
                receipt['scale'] = 1.0
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                mj.write_job(folder, latest)
            selected_scale = row.get('scale', 1.0)
            rotation = row.get('rotation')
            if row['kind'] == 'split':
                # Capacity on the unsplit source is zero by definition here; each
                # source plate was independently checked at authored size.
                capacity = 1
            else:
                capacity = await _heavy(orca_adapter.orca_plate_capacity, path, state,
                                        scale=selected_scale,
                                        **({'rotation': rotation, 'supports': bool(row.get('supports'))}
                                           if rotation else {}))
                if capacity < 1:
                    raise RuntimeError(f'Orca no longer verifies a fit for {row["label"]}')
            if selected_scale < 1.0:
                latest['scale'] = selected_scale
                receipt['scale'] = selected_scale
            if rotation:
                orientation = {k: row[k] for k in ('rotation', 'axis', 'dims_full_mm', 'supports', 'brim', 'label')}
                latest['orientation'] = orientation
                receipt['orientation'] = orientation
            mj.write_job(folder, latest)
        quantities = orca_adapter.quantity_buttons(capacity)
        chosen_quantity = 1
        if len(quantities) > 1:
            quantity_choices = quantity_options(capacity)
            qty_labels = [label for label, _ in quantity_choices]
            qty_prompt = (f"How many copies? This plate fits up to {capacity}. Tap a button "
                          f"or type any number from 1 to {capacity}.")
            live_key = (getattr(event, 'metadata', None) or {}).get('live_session_key')
            try:
                picked_quantity = await _ask(adapter, source, key, qty_prompt, qty_labels, timeout,
                                            parser=lambda text: str(parse_quantity(text, capacity)),
                                            live_key=live_key)
                chosen_quantity = (quantity_choices[picked_quantity][1]
                                   if isinstance(picked_quantity, int) else int(picked_quantity))
            except RuntimeError as exc:
                if 'valid button choice' not in str(exc):
                    raise
                await adapter.send(chat_id=source.chat_id,
                                   content='Pick a quantity button or type one number from 1 to '
                                           f'{capacity}. Nothing was changed.', metadata=metadata)
                return {'action': 'skip', 'reason': 'quantity choice unresolved'}
        latest['copies'] = chosen_quantity
        mj.write_job(folder, latest)
        receipt.update(status='COLORS_SAVED', color_decisions=validated, copies=chosen_quantity)
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        multi = len(manifest['parts']) > 1
        def _color_of(sel):
            sel = sel or {}
            color = str(sel.get('color') or '').strip()
            return ' '.join(v for v in (color[:1].upper() + color[1:], str(sel.get('material') or '')) if v) or f"Slot {sel.get('slot')}"
        if validated.get('mode') == 'single_color':
            names = _color_of(validated.get('selection'))
        else:
            labels = {row['key']: re.sub(r'^Choose the color/material for ', '', row.get('question', ''))
                      .split(' (')[0] for row in questions}
            names = ' · '.join(f"{labels.get(k, k)}: {_color_of(v)}" for k, v in validated.get('choices', {}).items())
        # Never promise "together" before slicing: the planner may still split with a stated reason.
        print_label = 'Slice and print now (bed is clear)'
        cancel_label = 'Cancel print request'
        caveat = (' Parts go on one multicolor bed when they fit; if they must split I will say why and ask '
                  'before starting each plate.' if multi and decisions['mode'] == 'per_part' else '')
        spool_text = await _spool_projection_text(mj, latest, manifest, state, chosen_quantity)
        source_estimate = _preview_estimate(latest.get('selected_source'))
        estimate_s = source_estimate[0] * chosen_quantity if source_estimate else None
        estimate_text = ('time after slicing' if estimate_s is None else
                         f"~{mj.human_dur(estimate_s + 300)}")
        if chosen_quantity and chosen_quantity != 1:
            estimate_text = f"{chosen_quantity} copies · " + estimate_text
        choice = await _ask(adapter, source, key,
            f'{names} · {estimate_text}'
            + ('\n' + spool_text if spool_text else '') + caveat,
            [print_label, 'Slice only', 'Stop with colors saved', cancel_label], timeout)
        if choice in (2, 3):
            receipt['status'] = 'CANCELLED' if choice == 3 else 'COLORS_SAVED_STOPPED'
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            message = ('Cancelled. Nothing was sliced, uploaded, or started.' if choice == 3
                       else 'Source inspected and colors saved. Stopped before slicing; nothing uploaded or started.')
            await adapter.send(chat_id=source.chat_id, content=message, metadata=metadata)
            return {'action': 'skip', 'reason': 'operator cancelled print request' if choice == 3 else 'operator stopped before slicing'}
        latest = json.loads(jp.read_text())
        if (latest.get('intake_id') != iid or latest.get('color_decisions') != validated
                or mj.file_sha256(latest['downloaded_file']) != decisions['source_sha256']):
            raise ValueError('source/job changed before slice approval; no handoff')
        receipt.update(status='SLICE_APPROVED', slice_approval={'intake_id': iid, 'source_sha256': decisions['source_sha256'],
                                                              'decisions_sha256': mj.decisions_digest(validated)})
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        mj._timing(jp, 'intake_slice_requested')
        prep_sent = False
        if choice == 0:
            # Acknowledge the tap before the slow slice, so a slicer failure is
            # never the first thing anyone hears. This is the only message
            # until "Print started" (or the failure that replaces it).
            pre_no = latest.get('print_number')
            pre_total = (f"~{mj.human_dur(estimate_s + 300)} total" if estimate_s is not None
                         else 'estimate after slicing')
            await adapter.send(chat_id=source.chat_id, metadata=metadata,
                               content=' · '.join(['Preparing to start'] + ([f'Print #{pre_no}'] if pre_no else [])
                                                  + [pre_total]))
            prep_sent = True
        if chosen_quantity and chosen_quantity > 1:
            out = await _heavy(mj.slice_job, str(jp), copies=chosen_quantity)
        else:
            out = await _heavy(mj.slice_job, str(jp))
        mj._timing(jp, 'intake_slice_returned')
        gcodes = [str(g) for g in (out if isinstance(out, list) else [out])]
        sliced = json.loads(jp.read_text())
        receipt.update(status='SLICED', sliced=True, gcodes=gcodes)
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        provenance = sliced.get('provenance') or {}
        if not provenance and (sliced.get('derived_plates') or []):
            provenance = (sliced['derived_plates'][0].get('provenance') or {})
        fallback = provenance.get('fallback') or {}
        if fallback.get('from') == 'OrcaSlicer':
            reason = str(fallback.get('reason') or 'Orca slicer failure')
            await adapter.send(chat_id=source.chat_id,
                               content=f'Bambu Studio sliced it because OrcaSlicer failed: {reason}.',
                               metadata=metadata)
        has_dur_q = has_duration_question(getattr(event, 'text', ''))
        if has_dur_q and gcodes:
            first_gcode = Path(gcodes[0])
            if first_gcode.is_file():
                dur_s = mj.gcode_estimate_s(first_gcode.read_text())
                if dur_s is not None:
                    dur_ans = (f"Estimated duration for {chosen_quantity} {'copy' if chosen_quantity == 1 else 'copies'}: "
                               f"{mj.human_dur(dur_s)} printing (warmup ~5 min separate). Total: ~{mj.human_dur(dur_s + 300)}.")
                    await adapter.send(chat_id=source.chat_id, content=dur_ans, metadata=metadata)
        first = Path(gcodes[0])
        exact_job, exact_plate = print_summary.find_job(str(first))
        if exact_job is None or exact_plate is None:
            raise ValueError('sliced artifact has no exact JOB.json record; refusing preparation message and start')
        actual_estimate = mj.gcode_estimate_s(first.read_text())
        slot_lines = ''
        try:
            from .multicolor_contract import describe_mapping, embedded_mapping
            _map = embedded_mapping(first.read_text(), state)
            if _map:
                slot_lines = describe_mapping(_map, state)
        except Exception as exc:  # a bad map is refused later by print-now; show why now
            slot_lines = f'Slot map problem: {exc}'
        estimate_text = (f"~{mj.human_dur(actual_estimate)} printing, ~{mj.human_dur(actual_estimate + 300)} total "
                         "including ~5 min warmup" if actual_estimate is not None else 'estimate unknown')
        plan_id = 'intake-' + iid[:16]
        target = {'plan_id': plan_id, 'part_id': 'plate1', 'copy': 1, 'gcode': str(first),
                  'gcode_sha256': mj.file_sha256(first), 'reprint': False}
        later = ''
        parts = []
        split = len(gcodes) > 1
        if split:
            plan = write_split_plan(jp, sliced, manifest, gcodes, plan_id)
            parts = plan['parts']
            listing = '\n'.join(f"- Plate {p['plate']}: {p['label']}" for p in parts)
            notice = (f"These print as {len(parts)} separate plates because {plan['split_reason']}.\n{listing}\n"
                      f"Only plate 1 starts from the next button. When it finishes and the bed is clear, type "
                      f"`/print-next {plan_id}` for a Start next plate button.")
            receipt.update(split_plan=plan_id, split_reason=plan['split_reason'])
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            await adapter.send(chat_id=source.chat_id, content=notice, metadata=metadata)
            later = f" Plate 1 of {len(parts)} only; then `/print-next {plan_id}` for the rest."
        if choice == 1 or split:
            # A start button bound to this exact plate, same machinery as /print-next.
            question = (f"Start plate 1 of {len(gcodes)} ({parts[0]['label']}) now? Starting uploads and prints immediately."
                        if split else 'Start this exact plate? Starting uploads and prints immediately.')
            if slot_lines:
                question = slot_lines + '\n' + question
            go = await _ask(adapter, source, key, question, [print_next.START_LABEL, print_next.CANCEL_LABEL], timeout)
            if go != 0:
                receipt['status'] = 'SLICED_NOT_STARTED'
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                tail = f' Plates stay ready: `/print-next {plan_id}`.' if split else ''
                await adapter.send(chat_id=source.chat_id, content='Sliced. Nothing uploaded or started.' + tail, metadata=metadata)
                return {'action': 'skip', 'reason': 'operator did not start the sliced plate'}
        # One click recorded: bed clear, bound to the exact JOB.json and G-code. print-now still runs every gate
        # (verify-gcode, live readiness, single-use approval, duplicate-start claim).
        receipt['bed_clear_approval'] = {'job_json': str(jp), 'gcode': str(first), 'gcode_sha256': target['gcode_sha256'],
                                         'granted_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'via': 'button'}
        receipt['status'] = 'START_REQUESTED'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        print_no = json.loads(jp.read_text()).get('print_number')
        total = estimate_text.split(', ', 1)[-1] if actual_estimate is not None else 'estimate after slicing'
        prep_msg = ' · '.join(['Preparing to start'] + ([f'Print #{print_no}'] if print_no else []) + [total])
        if slot_lines:
            prep_msg += '\n' + slot_lines
        if not prep_sent:
            await adapter.send(chat_id=source.chat_id, content=prep_msg, metadata=metadata)
        mj._timing(jp, 'intake_start_tapped')
        ok, tail = await print_next.start(target)
        mj._timing(jp, 'intake_start_returned', ok=bool(ok))
        receipt.update(status='STARTED' if ok else 'START_REFUSED', started=bool(ok))
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        if ok and print_next.still_preparing(tail):
            # "Preparing to start" is already posted; the listener posts the single "Print started".
            return {'action': 'skip', 'reason': 'sliced and start handled by button flow'}
        if ok:
            message = print_summary.format_started(exact_job, exact_plate) + later
        else:
            message = print_summary.scrub(tail)
        await adapter.send(chat_id=source.chat_id, content=message, metadata=metadata)
        return {'action': 'skip', 'reason': 'sliced and start handled by button flow'}
    except IntakeCancelled:
        receipt.update(status='CANCELLED', sliced=False, uploaded=False, started=False)
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        await adapter.send(chat_id=source.chat_id,
            content='Cancelled. Nothing sliced, uploaded or started.', metadata=metadata)
        return {'action': 'skip', 'reason': 'cancelled by operator'}
    except Exception as exc:
        receipt.update(status='FAILED', error=str(exc))
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        await adapter.send(chat_id=source.chat_id, content=f'New model preparation stopped: {exc}. Nothing sliced, uploaded or started.', metadata=metadata)
        return {'action': 'skip', 'reason': 'source-first intake failed closed'}
    finally:
        _LIVE_KEY.reset(live_token)
