from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ZOTERO_API_BASE_URL = "https://api.zotero.org"


@dataclass(frozen=True)
class ZoteroApiCredentials:
    api_key: str
    user_id: str


class ZoteroApiError(RuntimeError):
    pass


def load_dotenv_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def zotero_api_credentials(workspace: Path | None = None) -> ZoteroApiCredentials:
    env_values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        env_values = {**env_values, **load_dotenv_values(workspace / ".env")}
    api_key = os.environ.get("ZOTERO_API_KEY") or env_values.get("ZOTERO_API_KEY") or ""
    user_id = os.environ.get("ZOTERO_USER_ID") or env_values.get("ZOTERO_USER_ID") or ""
    if not api_key:
        raise ZoteroApiError("Missing ZOTERO_API_KEY")
    if not user_id:
        raise ZoteroApiError("Missing ZOTERO_USER_ID")
    return ZoteroApiCredentials(api_key=api_key, user_id=user_id)


def zotero_api_get(
    path: str,
    credentials: ZoteroApiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
    base_url: str = ZOTERO_API_BASE_URL,
) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        url,
        headers={
            "Zotero-API-Key": credentials.api_key,
            "Zotero-API-Version": "3",
            "Accept": "application/json",
        },
        method="GET",
    )
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ZoteroApiError(f"Zotero API request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise ZoteroApiError(f"Zotero API request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ZoteroApiError("Zotero API returned invalid JSON") from exc


def zotero_api_key_info(
    credentials: ZoteroApiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    data = zotero_api_get(f"keys/{credentials.api_key}", credentials, opener=opener)
    return data if isinstance(data, dict) else {}


def zotero_api_collections(
    credentials: ZoteroApiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
) -> list[dict[str, Any]]:
    data = zotero_api_get(f"users/{credentials.user_id}/collections?limit=100", credentials, opener=opener)
    if not isinstance(data, list):
        return []
    collections = []
    for item in data:
        if not isinstance(item, dict):
            continue
        item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        collections.append(
            {
                "key": item.get("key") or item_data.get("key"),
                "name": item_data.get("name"),
                "parent_key": item_data.get("parentCollection"),
                "version": item.get("version"),
                "source": "zotero_web_api",
            }
        )
    return collections


def zotero_api_readiness(
    credentials: ZoteroApiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    info = zotero_api_key_info(credentials, opener=opener)
    access = info.get("access") if isinstance(info.get("access"), dict) else {}
    user_access = access.get("user") if isinstance(access.get("user"), dict) else {}
    return {
        "version": 1,
        "user_id": credentials.user_id,
        "key_loaded": True,
        "key_has_write_access": bool(user_access.get("write")),
        "library_access": bool(user_access.get("library")),
        "notes_access": bool(user_access.get("notes")),
        "policy": "read_only_required",
    }
