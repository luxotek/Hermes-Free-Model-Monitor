"""What Hermes has configured vs what it actually used (config.yaml + agent.log)."""
import collections
import json
import os
import re
import subprocess

from nous_core import hermes_home

CALL_RE = re.compile(r"API call #\d+: model=(\S+) provider=(\S+)")
FALLBACK_RE = re.compile(r"Fallback activated: (\S+) → (\S+)")

# Raw `config get` output memoized for one configured_models() pass, so
# fallback_chain() can reuse the fallback_providers read instead of paying for a
# second CLI call on every deep refresh.
_RAW = {}

# The Hermes CLI launcher is a GUI app, but it hosts a ConPTY terminal, so on
# Windows a plain subprocess.run briefly creates a PseudoConsoleWindow (and
# steals focus) before the CLI finishes. CREATE_NO_WINDOW suppresses it.
CREATE_NO_WINDOW = 0x08000000


def _windowless_kwargs():
    """Extra subprocess kwargs that keep child processes from popping a window."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": startupinfo}


def run_hermes(args, timeout=15):
    """Run the Hermes CLI with output captured, without flashing a terminal window."""
    return subprocess.run(
        ["hermes", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        **_windowless_kwargs(),
    )


def _get(key):
    """Read one value from Hermes config via the CLI (never hand-edits config.yaml)."""
    if key in _RAW:
        return _RAW[key].strip()
    try:
        proc = run_hermes(["config", "get", key])
    except Exception:
        return ""
    out = proc.stdout if proc.returncode == 0 else ""
    _RAW[key] = out
    return out.strip()


def _parse_aux(raw):
    rows = []
    section = None
    provider = ""
    for line in raw.splitlines():
        head = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", line)
        if head:
            section = head.group(1)
            provider = ""
            continue
        prov = re.match(r"^\s+provider:\s*(\S+)", line)
        if prov and section:
            provider = prov.group(1).strip().strip("\"'")
            continue
        mod = re.match(r"^\s+model:\s*(.+?)\s*$", line)
        if mod and section:
            model = mod.group(1).strip().strip("\"'")
            if model:
                rows.append((section, provider, model))
    return rows


def _parse_fallback(raw):
    rows = []
    provider = ""
    for line in raw.splitlines():
        prov = re.match(r"\s*-\s+provider:\s*(\S+)", line)
        if prov:
            provider = prov.group(1).strip().strip("\"'")
        mod = re.match(r"\s+model:\s*(\S+)", line)
        if mod:
            rows.append((provider, mod.group(1).strip().strip("\"'")))
    return rows


def _parse_fallback_blocks(raw):
    """Parse plain `config get fallback_providers` YAML into full entry dicts.

    Used when the memoized text (or an older CLI without --json) is all we have;
    keeps every key on each entry, not just provider/model.
    """
    entries = []
    current = None
    for line in raw.splitlines():
        item = re.match(r"^\s*-\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if item:
            current = {}
            entries.append(current)
            current[item.group(1)] = item.group(2).strip().strip("\"'")
            continue
        field = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if field and current is not None:
            current[field.group(1)] = field.group(2).strip().strip("\"'")
    return entries


def fallback_chain():
    """The fallback chain exactly as configured, extra keys (base_url, api_key…) intact."""
    raw = _RAW.get("fallback_providers")
    if raw is None:
        proc = run_hermes(["config", "get", "fallback_providers", "--json"])
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "could not read fallbacks").strip())
        raw = proc.stdout
    try:
        data = json.loads(raw)
    except ValueError:
        data = _parse_fallback_blocks(raw)
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict) and entry.get("model")]


def set_fallbacks(entries):
    """Write the whole fallback chain back (order and extra keys preserved)."""
    _RAW.pop("fallback_providers", None)
    payload = json.dumps(entries, ensure_ascii=False)
    proc = run_hermes(["config", "set", "fallback_providers", payload], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "could not write fallbacks").strip())


def configured_models():
    """Every model Hermes has pinned: main, auxiliary tasks, fallback chain."""
    _RAW.clear()
    rows = []
    main = _get("model.default")
    if main:
        rows.append({
            "role": "main (default)",
            "provider": _get("model.provider") or "nous",
            "model": main,
        })
    for section, provider, model in _parse_aux(_get("auxiliary")):
        rows.append({"role": f"aux: {section}", "provider": provider or "?", "model": model})
    for index, (provider, model) in enumerate(_parse_fallback(_get("fallback_providers")), 1):
        rows.append({"role": f"fallback #{index}", "provider": provider or "?", "model": model})
    return rows


def recent_usage(lines=400):
    """Count recent API calls per model and note fallbacks from agent.log."""
    path = os.path.join(hermes_home(), "logs", "agent.log")
    counts = {}
    fallbacks = []
    last_model = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = collections.deque(fh, maxlen=lines)
    except OSError:
        return {"counts": counts, "fallbacks": fallbacks, "last": None}

    for line in tail:
        call = CALL_RE.search(line)
        if call:
            counts[call.group(1)] = counts.get(call.group(1), 0) + 1
            last_model = call.group(1)
            continue
        switched = FALLBACK_RE.search(line)
        if switched:
            fallbacks.append((switched.group(1), switched.group(2)))
    return {"counts": counts, "fallbacks": fallbacks, "last": last_model}
