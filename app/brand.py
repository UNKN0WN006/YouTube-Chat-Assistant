from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path

from fastapi import UploadFile

from .config import BRAND_DIR, MAX_LOGO_BYTES


CONFIG_FILE = BRAND_DIR / "brand.json"
ALLOWED_TYPES = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"name": "YouTube Assistant", "logo": "logo.svg"}


def brand_state() -> dict:
    config = _load_config()
    logo_name = config.get("logo", "logo.svg")
    logo_file = BRAND_DIR / logo_name
    version = int(logo_file.stat().st_mtime_ns) if logo_file.exists() else int(time.time())
    return {
        "name": config.get("name", "YouTube Assistant"),
        "logo_url": f"/static/brand/{logo_name}?v={version}",
        "version": str(version),
    }


def brand_logo_data() -> dict:
    config = _load_config()
    logo_name = config.get("logo", "logo.svg")
    logo_file = BRAND_DIR / logo_name
    if not logo_file.exists():
        raise FileNotFoundError("Logo file is missing.")

    mime = mimetypes.guess_type(logo_file.name)[0] or "image/svg+xml"
    encoded = base64.b64encode(logo_file.read_bytes()).decode("ascii")
    state = brand_state()
    return {
        "version": state["version"],
        "name": state["name"],
        "data_url": f"data:{mime};base64,{encoded}",
    }


async def save_logo(file: UploadFile) -> dict:
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_TYPES.get(content_type)
    if not extension:
        raise ValueError("Use SVG, PNG, JPG, or WebP for the logo.")

    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be smaller than 1.5 MB.")

    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    new_name = f"logo-current{extension}"
    target = BRAND_DIR / new_name
    target.write_bytes(data)

    config = _load_config()
    old_name = config.get("logo")
    config["logo"] = new_name
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

    if old_name and old_name.startswith("logo-current") and old_name != new_name:
        old_path = BRAND_DIR / old_name
        if old_path.exists():
            old_path.unlink()

    return brand_state()
