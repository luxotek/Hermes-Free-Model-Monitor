"""Fetch the live free-model catalog from the Nous Portal + inference API."""
import json
import os
import re
import urllib.request


def hermes_home():
    """Locate the Hermes home directory that holds auth.json."""
    candidates = [
        os.environ.get("HERMES_HOME"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes"),
        os.path.expanduser("~/.hermes"),
    ]
    for cand in candidates:
        if cand and os.path.isfile(os.path.join(cand, "auth.json")):
            return cand
    return None


def load_auth():
    home = hermes_home()
    if not home:
        raise RuntimeError(
            "Could not find Hermes auth.json. Run `hermes setup` / log in first."
        )
    with open(os.path.join(home, "auth.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    prov = data["providers"]["nous"]
    # The base URLs are read from the login, never assumed: a build that
    # hardcodes them would keep talking to the old host after a migration.
    portal = prov.get("portal_base_url")
    inference = prov.get("inference_base_url")
    if not portal or not inference:
        raise RuntimeError(
            "auth.json is missing portal_base_url / inference_base_url — "
            "run `hermes setup` again."
        )
    return {
        "token": prov["access_token"],
        "portal": portal.rstrip("/"),
        "inference": inference.rstrip("/"),
        "portal_host": re.sub(r"^[a-z]+://", "", portal.rstrip("/")).split("/")[0],
    }


def _get_json_http(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"), strict=False)


def _get_json(url, token):
    """GET with a Bearer token — what the Portal and inference APIs both take."""
    return _get_json_http(url, {"Authorization": "Bearer " + token, "User-Agent": "hfmm/1.0"})


def _price_is_free(value):
    try:
        return float(str(value).replace("$", "").strip() or "nan") == 0.0
    except ValueError:
        return False


TEMP_TOKENS = ("preview", "alpha", "beta", "exp")


def _temp_type(slug):
    """Lifecycle marker from a slug: preview / alpha / beta / exp (whole tokens)."""
    tokens = re.split(r"[/:._-]", str(slug or "").lower())
    for token in TEMP_TOKENS:
        if token in tokens:
            return token
    return ""


INPUT_ORDER = ("text", "image", "video", "audio")


def _normalize_inputs(modalities):
    """Canonical modality order: text first (it is always there), then the rest."""
    items = {str(m).strip() for m in (modalities or []) if str(m).strip()}
    return sorted(items, key=lambda m: (
        INPUT_ORDER.index(m) if m in INPUT_ORDER else len(INPUT_ORDER), m))


def _merge_inputs(*values):
    """Union of comma-separated modality strings, in canonical order."""
    joined = []
    for value in values:
        for item in str(value or "").split(","):
            item = item.strip()
            if item and item not in joined:
                joined.append(item)
    return ", ".join(_normalize_inputs(joined))


def _catalog_extra(model):
    """Reported facts that are too wide for a column but help on selection."""
    provider = model.get("top_provider") or {}
    reasoning = model.get("reasoning")
    if isinstance(reasoning, dict):
        if reasoning.get("mandatory"):
            reason_text = "mandatory"
        elif reasoning.get("default_enabled"):
            reason_text = "default-on"
        else:
            reason_text = "optional"
    else:
        reason_text = ""
    analysis = ((model.get("benchmarks") or {}).get("artificial_analysis") or {})
    return {
        "description": (model.get("description") or "").strip(),
        "moderated": provider.get("is_moderated"),
        "reasoning": reason_text,
        "aa": {key: analysis.get(key) for key in
                ("intelligence_index", "coding_index", "agentic_index")},
        "hf": model.get("hugging_face_id"),
        "slug": model.get("canonical_slug"),
        "synthesized": bool(model.get("synthesizedFreeVariant")),
        "cutoff": model.get("knowledge_cutoff"),
    }


def _catalog_info(model):
    """Context / modality facts for any catalog entry, free or paid."""
    arch = model.get("architecture") or {}
    modalities = arch.get("input_modalities") or ["text"]
    slug = model.get("id") or model.get("model") or ""
    return {
        "context": model.get("context_length") or model.get("contextLength"),
        "inputs": ", ".join(_normalize_inputs(modalities)),
        "vision": "image" in modalities,
        "video": "video" in modalities,
        "temp": _temp_type(slug),
        "end": model.get("expiration_date") or "",
        "output": (model.get("top_provider") or {}).get("max_completion_tokens"),
        "created": model.get("created"),
        # This endpoint is Nous's own /models, so its entries are served by
        # Nous unless the portal's per-model `source` says otherwise.
        "route": "local",
        "extra": _catalog_extra(model),
    }


def _catalog_row(model, source="catalog"):
    pricing = model.get("pricing") or {}
    if not (_price_is_free(pricing.get("prompt")) and _price_is_free(pricing.get("completion"))):
        return None
    row = _catalog_info(model)
    row["name"] = model.get("id")
    row["compaction"] = False
    row["source"] = source
    # This catalog IS Nous's inference /models endpoint, so its entries are
    # served by Nous unless the portal says otherwise.
    row["route"] = "local"
    return row


_OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_HEADERS = {"User-Agent": "hfmm/1.0"}

_openrouter_cache = {}


def _env_openrouter_key():
    """OpenRouter token lives in Hermes's .env, the same file the CLI loads."""
    home = hermes_home()
    if not home:
        return None
    try:
        with open(os.path.join(home, ".env"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _pool_openrouter_key():
    """Also accept a pooled credential from auth.json if no .env is present."""
    home = hermes_home()
    if not home:
        return None
    try:
        with open(os.path.join(home, "auth.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    pool = (data.get("credential_pool") or {}).get("openrouter")
    if not isinstance(pool, list):
        return None
    for entry in pool:
        if isinstance(entry, dict):
            for field in ("api_key", "access_token", "key"):
                if entry.get(field):
                    return entry[field]
    return None


def _openrouter_key_accepts(key):
    req = urllib.request.Request(
        _OPENROUTER_KEY_URL,
        headers={"Authorization": f"Bearer {key}", **_OPENROUTER_HEADERS},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def openrouter_key():
    """Return a valid OpenRouter token, checked once per process, or None."""
    cached = _openrouter_cache.get("key")
    if cached is not None:
        return cached
    for candidate in (_env_openrouter_key, _pool_openrouter_key):
        key = candidate()
        if key and _openrouter_key_accepts(key):
            _openrouter_cache["key"] = key
            return key
    _openrouter_cache["key"] = None
    return None


def openrouter_pool():
    """The free-tier daily request pool from OpenRouter's /api/v1/key.

    ``free_model_daily_requests`` is the shared 50/day budget across every free
    model, so it is the number that decides whether a free chain "allows heavy
    use". None when there is no token or the payload has no such field.
    """
    key = openrouter_key()
    if not key:
        return None
    try:
        payload = _get_json_http(
            _OPENROUTER_KEY_URL,
            {"Authorization": f"Bearer {key}", **_OPENROUTER_HEADERS},
        )
    except Exception:  # noqa: BLE001
        return None
    pool = (payload.get("data") or {}).get("free_model_daily_requests")
    if not isinstance(pool, dict):
        return None
    return {
        "used": pool.get("used"),
        "limit": pool.get("limit"),
        "remaining": pool.get("remaining"),
    }


def fetch_free_models(permanent_only=True):
    """Return (list_of_free_models, meta_dict).

    permanent_only drops preview/alpha/beta/exp models and anything with an
    expiration_date, so the list holds models worth building a long-term
    fallback chain on.
    """
    auth = load_auth()
    portal = _get_json(auth["portal"] + "/api/nous/recommended-models", auth["token"])
    catalog = _get_json(auth["inference"] + "/models", auth["token"]).get("data", [])

    by_id = {}
    for model in catalog:
        row = _catalog_row(model)
        if row:
            by_id[row["name"]] = row

    # Context/flags for every catalog entry (paid ones too), so the config tab
    # can show them for models that are not on the free list.
    lookup = {}
    for model in catalog:
        rid = model.get("id")
        if rid:
            lookup[rid] = _catalog_info(model)

    by_name = {}

    def add(record, source):
        name = record["name"]
        record.setdefault("temp", _temp_type(name))
        record.setdefault("end", "")
        record.setdefault("output", None)
        record.setdefault("created", None)
        record.setdefault("extra", None)
        record.setdefault("route", "")
        existing = by_name.get(name)
        if existing is None:
            merged = dict(record, sources={source})
            by_name[name] = merged
            return
        existing["sources"].add(source)
        if not existing["route"]:
            existing["route"] = record["route"]
        existing["vision"] = existing["vision"] or record["vision"]
        existing["video"] = existing["video"] or record["video"]
        existing["compaction"] = existing["compaction"] or record["compaction"]
        if not existing["context"]:
            existing["context"] = record["context"]
        if record["inputs"] != "text":
            existing["inputs"] = _merge_inputs(existing["inputs"], record["inputs"])
        if not existing["temp"]:
            existing["temp"] = record["temp"]
        if not existing["end"]:
            existing["end"] = record["end"]
        if not existing["output"]:
            existing["output"] = record["output"]
        if not existing["created"]:
            existing["created"] = record["created"]
        extra = record.get("extra")
        if extra:
            target = existing.get("extra") or {}
            for key, value in extra.items():
                if not target.get(key) and value not in (None, "", [], {}):
                    target[key] = value
            existing["extra"] = target

    def add_portal(rec, catalog_hit):
        add(
            {
                "name": rec["modelName"],
                "context": catalog_hit.get("context") or rec.get("contextLength"),
                "inputs": catalog_hit.get("inputs")
                or ("text, image" if rec.get("isVisionModel") else "text"),
                "vision": bool(rec.get("isVisionModel")) or catalog_hit.get("vision", False),
                "video": catalog_hit.get("video", False),
                "compaction": bool(rec.get("isCompactionModel")),
                "output": catalog_hit.get("output"),
                "created": catalog_hit.get("created"),
                "extra": catalog_hit.get("extra"),
                # The portal's own routing field: "local" (Nous) or "openrouter".
                "route": rec.get("source") or "",
            },
            "portal",
        )

    for rec in portal.get("freeRecommendedModels") or []:
        slug = rec.get("modelName")
        if slug:
            add_portal(rec, by_id.get(slug, {}))

    for key in ("freeRecommendedVisionModel", "freeRecommendedCompactionModel"):
        rec = portal.get(key)
        if rec and rec.get("modelName"):
            add_portal(rec, by_id.get(rec["modelName"], {}))

    for slug, row in sorted(by_id.items()):
        if slug not in by_name:
            add(row, "catalog")

    # The models endpoint is public — no token needed to see the catalogue. Send
    # one when we have it (the authenticated payload is the set the key can
    # actually call) and fall back to the unauthenticated list when we don't.
    or_key = openrouter_key()
    or_headers = dict(_OPENROUTER_HEADERS)
    if or_key:
        or_headers["Authorization"] = f"Bearer {or_key}"
    or_count = 0
    try:
        payload = _get_json_http(_OPENROUTER_MODELS_URL, or_headers)
    except Exception:  # noqa: BLE001
        payload = {}
    for model in payload.get("data", []):
        rid = model.get("id") or model.get("model") or ""
        pricing = model.get("pricing") or {}
        # Free on OpenRouter: the :free marker, or $0 input AND $0 output.
        free_marker = rid.endswith(":free")
        zero_in_out = (_price_is_free(pricing.get("prompt"))
                       and _price_is_free(pricing.get("completion")))
        if not (free_marker or zero_in_out):
            continue
        row = dict(_catalog_info(model))
        row["name"] = model.get("id")
        row["compaction"] = False
        row["source"] = "openrouter"
        # These came from OpenRouter's own models endpoint.
        row["route"] = "openrouter"
        extra = dict(row.get("extra") or {})
        extra["or_slug"] = model.get("id")
        row["extra"] = extra
        add(row, "openrouter")
        or_count += 1

    results = []
    for name, rec in sorted(by_name.items()):
        sources = rec.pop("sources")
        if sources == {"portal", "catalog"}:
            rec["source"] = "portal+catalog"
        else:
            rec["source"] = next(iter(sources))
        results.append(rec)

    # Free rows carry portal-derived context/flags for models the catalog does
    # not describe; fold them into the lookup as well.
    for rec in results:
        info = lookup.setdefault(rec["name"], {})
        info.setdefault("context", rec.get("context"))
        info.setdefault("inputs", rec.get("inputs"))
        info.setdefault("vision", rec.get("vision", False))
        info.setdefault("video", rec.get("video", False))
        info.setdefault("compaction", rec.get("compaction", False))
        info.setdefault("temp", rec.get("temp"))
        info.setdefault("end", rec.get("end"))
        info.setdefault("output", rec.get("output"))
        info.setdefault("created", rec.get("created"))
        info.setdefault("extra", rec.get("extra"))

    if permanent_only:
        results = [r for r in results if not r.get("temp") and not r.get("end")]

    return results, {
        "catalog_rows": len(catalog),
        "free_count": len(results),
        "catalog_ids": [m.get("id") for m in catalog if m.get("id")],
        "openrouter": or_count,
        "catalog_lookup": lookup,
    }
