"""Fetch the live free-model catalog from the Nous Portal + inference API."""
import json
import os
import urllib.request

DEFAULT_PORTAL = "https://portal.nousresearch.com"
DEFAULT_INFERENCE = "https://inference-api.nousresearch.com/v1"


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
    return {
        "token": prov["access_token"],
        "portal": prov.get("portal_base_url", DEFAULT_PORTAL).rstrip("/"),
        "inference": prov.get("inference_base_url", DEFAULT_INFERENCE).rstrip("/"),
    }


def _get_json(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "User-Agent": "hfmm/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"), strict=False)


def _price_is_free(value):
    try:
        return float(str(value).replace("$", "").strip() or "nan") == 0.0
    except ValueError:
        return False


def _catalog_row(model):
    pricing = model.get("pricing") or {}
    if not (_price_is_free(pricing.get("prompt")) and _price_is_free(pricing.get("completion"))):
        return None
    arch = model.get("architecture") or {}
    modalities = arch.get("input_modalities") or ["text"]
    return {
        "name": model.get("id"),
        "context": model.get("context_length") or model.get("contextLength"),
        "inputs": ", ".join(modalities),
        "vision": "image" in modalities,
        "video": "video" in modalities,
        "compaction": False,
        "source": "catalog",
    }


def fetch_free_models():
    """Return (list_of_free_models, meta_dict)."""
    auth = load_auth()
    portal = _get_json(auth["portal"] + "/api/nous/recommended-models", auth["token"])
    catalog = _get_json(auth["inference"] + "/models", auth["token"]).get("data", [])

    by_id = {}
    for model in catalog:
        row = _catalog_row(model)
        if row:
            by_id[row["name"]] = row

    by_name = {}

    def add(record, source):
        name = record["name"]
        existing = by_name.get(name)
        if existing is None:
            merged = dict(record, sources={source})
            by_name[name] = merged
            return
        existing["sources"].add(source)
        existing["vision"] = existing["vision"] or record["vision"]
        existing["video"] = existing["video"] or record["video"]
        existing["compaction"] = existing["compaction"] or record["compaction"]
        if not existing["context"]:
            existing["context"] = record["context"]
        if record["inputs"] != "text":
            existing["inputs"] = record["inputs"]

    for rec in portal.get("freeRecommendedModels") or []:
        slug = rec.get("modelName")
        if not slug:
            continue
        catalog_hit = by_id.get(slug, {})
        add(
            {
                "name": slug,
                "context": catalog_hit.get("context") or rec.get("contextLength"),
                "inputs": catalog_hit.get("inputs")
                or ("text, image" if rec.get("isVisionModel") else "text"),
                "vision": bool(rec.get("isVisionModel")) or catalog_hit.get("vision", False),
                "video": catalog_hit.get("video", False),
                "compaction": bool(rec.get("isCompactionModel")),
            },
            "portal",
        )

    for key in ("freeRecommendedVisionModel", "freeRecommendedCompactionModel"):
        rec = portal.get(key)
        if not rec or not rec.get("modelName"):
            continue
        catalog_hit = by_id.get(rec["modelName"], {})
        add(
            {
                "name": rec["modelName"],
                "context": catalog_hit.get("context") or rec.get("contextLength"),
                "inputs": catalog_hit.get("inputs")
                or ("text, image" if rec.get("isVisionModel") else "text"),
                "vision": bool(rec.get("isVisionModel")) or catalog_hit.get("vision", False),
                "video": catalog_hit.get("video", False),
                "compaction": bool(rec.get("isCompactionModel")),
            },
            "portal",
        )

    for slug, row in sorted(by_id.items()):
        if slug not in by_name:
            add(row, "catalog")

    results = []
    for name, rec in sorted(by_name.items()):
        sources = rec.pop("sources")
        if sources == {"portal", "catalog"}:
            rec["source"] = "portal+catalog"
        else:
            rec["source"] = next(iter(sources))
        results.append(rec)
    return results, {
        "catalog_rows": len(catalog),
        "free_count": len(results),
        "catalog_ids": [m.get("id") for m in catalog if m.get("id")],
    }
