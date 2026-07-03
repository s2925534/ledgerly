from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from researchboss.core.yamlio import read_yaml


OPENAI_API_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class OpenAiCredentials:
    api_key: str


class OpenAiError(RuntimeError):
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


def openai_credentials(workspace: Path | None = None) -> OpenAiCredentials:
    env_values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        env_values = {**env_values, **load_dotenv_values(workspace / ".env")}
    api_key = os.environ.get("OPENAI_API_KEY") or env_values.get("OPENAI_API_KEY") or ""
    if not api_key:
        raise OpenAiError("Missing OPENAI_API_KEY")
    return OpenAiCredentials(api_key=api_key)


def workspace_ai_settings(workspace: Path) -> dict[str, Any]:
    settings = read_yaml(workspace / "app-settings.local.yaml")
    ai_settings = settings.get("ai")
    return ai_settings if isinstance(ai_settings, dict) else {}


def require_ai_flag(ai: bool) -> None:
    if not ai:
        raise OpenAiError("Pass --ai to explicitly allow this OpenAI action.")


def openai_get(
    path: str,
    credentials: OpenAiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
    base_url: str = OPENAI_API_BASE_URL,
) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {credentials.api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OpenAiError(f"OpenAI request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise OpenAiError(f"OpenAI request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAiError("OpenAI returned invalid JSON") from exc


def openai_readiness(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    live: bool = False,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    ai_settings = workspace_ai_settings(workspace)
    openai_settings = {}
    providers = ai_settings.get("providers") if isinstance(ai_settings.get("providers"), dict) else {}
    if isinstance(providers.get("openai"), dict):
        openai_settings = providers["openai"]

    report: dict[str, Any] = {
        "version": 1,
        "provider": "openai",
        "key_loaded": bool(credentials.api_key),
        "key_exposed": False,
        "workspace_ai_enabled": bool(ai_settings.get("enabled")),
        "openai_provider_enabled": bool(openai_settings.get("enabled")),
        "default_model": openai_settings.get("default_model"),
        "live_request_performed": False,
        "policy": "explicit_ai_flag_required",
    }

    if live:
        data = openai_get("models", credentials, opener=opener)
        models = data.get("data") if isinstance(data, dict) else []
        report["live_request_performed"] = True
        report["api_reachable"] = True
        report["model_count"] = len(models) if isinstance(models, list) else 0

    return report
