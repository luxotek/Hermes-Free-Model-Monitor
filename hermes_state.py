"""What Hermes has configured vs what it actually used (config.yaml + agent.log)."""
import collections
import os
import re
import subprocess

from nous_core import hermes_home

CALL_RE = re.compile(r"API call #\d+: model=(\S+) provider=(\S+)")
FALLBACK_RE = re.compile(r"Fallback activated: (\S+) → (\S+)")


def _get(key):
    """Read one value from Hermes config via the CLI (never hand-edits config.yaml)."""
    try:
        proc = subprocess.run(
            ["hermes", "config", "get", key],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


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
        prov = re.match(r"\s*-\s*provider:\s*(\S+)", line)
        if prov:
            provider = prov.group(1).strip().strip("\"'")
        mod = re.match(r"\s+model:\s*(\S+)", line)
        if mod:
            rows.append((provider, mod.group(1).strip().strip("\"'")))
    return rows


def configured_models():
    """Every model Hermes has pinned: main, auxiliary tasks, fallback chain."""
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
