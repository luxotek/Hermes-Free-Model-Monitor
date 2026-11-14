"""Off-catalog ('stealth') models: watchlist mined from agent.log + liveness probes."""
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request

from nous_core import load_auth

WATCH_RE = re.compile(r"stealth/[A-Za-z0-9._-]+")
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stealth_state.json")


def log_path():
    home = (
        os.environ.get("HERMES_HOME")
        or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
    )
    return os.path.join(home, "logs", "agent.log")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            state.setdefault("watch", {})
            state.setdefault("discovered", [])
            state.setdefault("settings", {})
            return state
    except (OSError, ValueError):
        pass
    return {"watch": {}, "discovered": [], "settings": {}}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    except OSError:
        pass


def mine_watchlist(state=None):
    """Count stealth/* mentions in agent.log, refreshing last_seen per slug."""
    if state is None:
        state = load_state()
    try:
        fh = open(log_path(), encoding="utf-8", errors="replace")
    except OSError:
        return rows(state)
    counts = {}
    last_seen = {}
    with fh:
        for line in fh:
            for slug in set(WATCH_RE.findall(line)):
                counts[slug] = counts.get(slug, 0) + 1
                match = TS_RE.match(line)
                if match:
                    last_seen[slug] = match.group(1)
    for slug, n in counts.items():
        entry = state["watch"].setdefault(slug, {"slug": slug, "origin": "log"})
        entry["calls"] = n
        entry["last_seen"] = last_seen.get(slug, "")
    save_state(state)
    return rows(state)


def rows(state):
    out = []
    for slug, entry in sorted(
        state["watch"].items(), key=lambda kv: -(kv[1].get("calls") or 0)
    ):
        probe = entry.get("probe") or {}
        out.append({
            "slug": slug,
            "calls": entry.get("calls", 0),
            "last_seen": entry.get("last_seen", ""),
            "origin": entry.get("origin", "log"),
            "state": probe.get("state", "unprobed"),
            "detail": probe.get("detail", ""),
            "ts": probe.get("ts", ""),
        })
    return out


def parse_alternates(text):
    match = re.search(r'"alternates"\s*:\s*\[([^\]]*)\]', text)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def probe(slug):
    """One-token chat completion to test whether a model still answers."""
    auth = load_auth()
    body = json.dumps({
        "model": slug,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        auth["inference"] + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + auth["token"],
            "Content-Type": "application/json",
            "User-Agent": "hfmm/1.0",
        },
    )
    started = time.time()
    ms = lambda: int((time.time() - started) * 1000)  # noqa: E731
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
            ok = bool(json.loads(raw).get("choices"))
            return {"state": "alive" if ok else "error", "detail": f"HTTP {resp.status}", "ms": ms()}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        alts = parse_alternates(raw)
        if exc.code == 404:
            detail = "HTTP 404 (no such model)"
        elif exc.code == 429:
            detail = "HTTP 429 (busy — may still be alive)"
        else:
            detail = f"HTTP {exc.code}: {raw[:120]}"
        return {"state": {404: "missing", 429: "rate_limited"}.get(exc.code, "error"),
                "detail": detail, "alternates": alts, "ms": ms()}
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "detail": str(exc)[:160], "ms": ms()}


def record_probe(state, slug, result):
    entry = state["watch"].setdefault(slug, {"slug": slug, "origin": "manual"})
    entry["probe"] = {
        "state": result["state"],
        "detail": result.get("detail", ""),
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    found = []
    for alt in result.get("alternates") or []:
        if alt in state["watch"]:
            continue
        state["watch"][alt] = {
            "slug": alt,
            "origin": "429 alternates",
            "calls": 0,
            "found_by": slug,
        }
        found.append(alt)
    save_state(state)
    return found