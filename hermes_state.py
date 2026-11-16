"""What Hermes has configured vs what it actually used (config.yaml + agent.log)."""
import collections
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request

from nous_core import hermes_home, load_auth

# One `hermes config get` call per key; see configured_models().
_CONFIG_KEYS = ("model.default", "model.provider", "auxiliary", "fallback_providers")

CALL_RE = re.compile(r"API call #\d+: model=(\S+) provider=(\S+)")
FALLBACK_RE = re.compile(r"Fallback activated: (\S+) → (\S+) \((\S+)\)")

# `API call failed (attempt 1/3[, not retryable]) error_type=… thread=… provider=…
#  base_url=… model=… summary=…` — the one line that names the model that failed.
FAIL_RE = re.compile(
    r"API call failed \(attempt (\d)/(\d)(?:, not retryable)?\) "
    r"error_type=(\w+) thread=\S+ provider=(\S+) base_url=\S+ model=(\S+) summary=(.*)"
)
# The 429 body carries the server's asked-for delay; only lines that also name a
# model (quoted, or a `model=` field) can attribute it.
RETRY_AFTER_RE = re.compile(r"'retry_after':\s*(\d+)")
QUOTED_MODEL_RE = re.compile(r"model '([^']+)'")
STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

ERROR_LABELS = {
    "RateLimitError": "429 rate limit",
    "NotFoundError": "404 gone",
    "APIError": "upstream idle",
    "AuthenticationError": "401 auth",
    "PermissionDeniedError": "403 denied",
    "BadRequestError": "400 bad request",
    "TimeoutError": "timeout",
}

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


# The portal reports where each model is served as `source`: "local" is Nous's
# own inference, "openrouter" is the OpenRouter provider. Hermes names the first
# one "nous", which is the only translation in this table — everything else is
# read straight off the API response.
ROUTE_PROVIDER = {"local": "nous", "openrouter": "openrouter"}


def provider_for_route(route):
    """Hermes provider id for a model's reported route; None when unknown."""
    return ROUTE_PROVIDER.get(str(route or "").strip().lower())


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
    # `hermes config get` takes one key at a time and costs ~1.2 s per call, so
    # the four reads run concurrently instead of serially.
    out = {}

    def one(key):
        try:
            out[key] = _get(key)
        except Exception:
            out[key] = ""

    workers = [threading.Thread(target=one, args=(key,)) for key in _CONFIG_KEYS]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    rows = []
    main = out.get("model.default", "")
    if main:
        rows.append({
            "role": "main (default)",
            # Hermes's own config value, never a guess: when it is unset the
            # app falls back to the route the model was reported on.
            "provider": out.get("model.provider", ""),
            "model": main,
        })
    for section, provider, model in _parse_aux(out.get("auxiliary", "")):
        rows.append({"role": f"aux: {section}", "provider": provider or "?", "model": model})
    for index, (provider, model) in enumerate(
        _parse_fallback(out.get("fallback_providers", "")), 1
    ):
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


def _error_label(error_type, summary):
    """Plain-language label for a failure; the two 429 flavours read differently."""
    if error_type == "RateLimitError":
        if "fair-share" in summary:
            return "429 rate limit"
        if "capacity" in summary:
            return "429 at capacity"
    return ERROR_LABELS.get(error_type, error_type)


def _duration(seconds):
    """6790 -> '1h53m', 53 -> '53s'. '' when unreadable."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def troubleshooting(lines=None):
    """Per-model trouble mined from agent.log.

    ``calls``     how many `API call #N` lines each slug has (your recent load)
    ``errors``    the last failure per slug: label, how many, when, and the
                  server's asked-for delay when one is attributable
    ``fallbacks`` the last `Fallback activated: A → B` each slug took part in,
                  as source (→) or target (←), with that pair's count
    ``retry``     last `retry_after` seen for a slug, from a line that names it

    ``lines`` caps the scan; None reads the whole log, which is what the config
    tab wants — a model that 404'd once last week is still a dead fallback slot.
    """
    path = os.path.join(hermes_home(), "logs", "agent.log")
    calls = {}
    errors = {}
    retry = {}
    pair_counts = collections.Counter()
    last_event = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = collections.deque(fh, maxlen=lines) if lines else fh
            for line in tail:
                stamp = STAMP_RE.match(line)
                stamp = stamp.group(1) if stamp else ""

                call = CALL_RE.search(line)
                if call:
                    calls[call.group(1)] = calls.get(call.group(1), 0) + 1
                    continue

                failed = FAIL_RE.search(line)
                if failed:
                    slug = failed.group(5)
                    rec = errors.get(slug) or {"count": 0}
                    rec["count"] += 1
                    rec["label"] = _error_label(failed.group(3), failed.group(6))
                    rec["summary"] = failed.group(6).strip()
                    rec["last"] = stamp
                    errors[slug] = rec
                    continue

                switched = FALLBACK_RE.search(line)
                if switched:
                    src, dst, provider = switched.group(1), switched.group(2), switched.group(3)
                    pair_counts[(src, dst)] += 1
                    last_event[src] = (stamp, "→", dst, provider, (src, dst))
                    last_event[dst] = (stamp, "←", src, provider, (src, dst))
                    continue

                asked = RETRY_AFTER_RE.search(line)
                if not asked:
                    continue
                quoted = QUOTED_MODEL_RE.search(line)
                slug = quoted.group(1) if quoted else None
                if slug:
                    retry[slug] = int(asked.group(1))
    except OSError:
        return {"calls": calls, "errors": errors, "fallbacks": {}, "retry": retry}

    fallbacks = {}
    for slug, (stamp, dirn, other, provider, key) in last_event.items():
        fallbacks[slug] = {
            "dir": dirn, "other": other, "provider": provider,
            "count": pair_counts[key], "last": stamp,
        }
    return {"calls": calls, "errors": errors, "fallbacks": fallbacks, "retry": retry}


def probe_rate_limit(model, timeout=40):
    """One tiny completion to read the account's live rate-limit bucket.

    The `x-ratelimit-*` response headers are the only place Nous publishes how
    close the account is to its fair-share limit (50 requests / 60 s, 2100 / h).
    They come back on a 429 too, so a refusal still answers the question.
    """
    auth = load_auth()
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        auth["inference"] + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + auth["token"],
            "Content-Type": "application/json",
            "User-Agent": "hfmm/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = resp.status
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in exc.headers.items()}
        status = exc.code
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "model": model}

    def integer(key):
        try:
            return int(str(headers.get(key, "")).strip())
        except (TypeError, ValueError):
            return None

    def number(key):
        try:
            return float(str(headers.get(key, "")).strip())
        except (TypeError, ValueError):
            return None

    return {
        "model": model,
        "status": status,
        "limit": integer("x-ratelimit-limit-requests"),
        "remaining": integer("x-ratelimit-remaining-requests"),
        "reset": number("x-ratelimit-reset-requests"),
        "limit_1h": integer("x-ratelimit-limit-requests-1h"),
        "remaining_1h": integer("x-ratelimit-remaining-requests-1h"),
        "policy": headers.get("ratelimit-policy", ""),
    }

