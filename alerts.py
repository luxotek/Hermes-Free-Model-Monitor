"""Model transition alerts and a Windows taskbar flash helper."""
import ctypes


def classify_transition(previous, current):
    """Return (level, description) for a status change, or None."""
    if not previous or previous == current:
        return None
    if current == "free":
        return "info", "is free again"
    if current == "missing":
        return "critical", "is gone from the catalog"
    if current == "paid":
        if previous == "free":
            return "critical", "no longer free (now paid)"
        return "warn", "is listed again, but paid"
    return None


def compute_alerts(previous_map, rows, free_names, catalog_ids):
    """Compare current classifications against the stored per-role map.

    Returns (alerts, current_map) where alerts are {key, level, text}.
    """
    alerts = []
    current = {}

    for row in rows:
        role = row["role"]
        slug = row["model"]
        if slug in free_names:
            status = "free"
        elif slug in catalog_ids or slug.split(":", 1)[0] in catalog_ids:
            status = "paid"
        else:
            status = "missing"
        current[role] = {"model": slug, "status": status}
        change = classify_transition((previous_map.get(role) or {}).get("status"), status)
        if change:
            level, tail = change
            alerts.append({"key": role, "level": level, "text": f"{role}: {slug} {tail}"})

    return alerts, current


class _FlashInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hwnd", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("uCount", ctypes.c_uint),
        ("dwTimeout", ctypes.c_uint),
    ]


def flash_taskbar(root, count=3):
    """Flash the window's taskbar button (best effort, no-op elsewhere)."""
    try:
        info = _FlashInfo()
        info.cbSize = ctypes.sizeof(_FlashInfo)
        info.hwnd = root.winfo_id()
        info.dwFlags = 0x02 | 0x0C  # FLASHW_TRAY | FLASHW_TIMERNOFG
        info.uCount = count
        info.dwTimeout = 0
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass