from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from .config import Settings
from .http import request_json


@dataclass
class ProviderResult:
    provider: str
    model: str
    content: str
    parsed: dict[str, Any]
    elapsed_seconds: float
    usage: dict[str, Any]


@dataclass
class ResearchResult:
    content: str
    sources: list[dict[str, str]]
    model: str
    elapsed_seconds: float
    usage: dict[str, Any]


class Provider(Protocol):
    name: str
    model: str

    def generate(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> ProviderResult: ...

    def healthcheck(self) -> dict[str, Any]: ...


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Provider returned invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise RuntimeError("Provider response must be a JSON object")
    return parsed


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # Gemini supports a useful JSON Schema subset and rejects some standard fields.
    unsupported = {"$schema", "$id", "$defs", "definitions", "additionalProperties"}

    def json_type(value: Any) -> str | None:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, str):
            return "string"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        return None

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {
                key: clean(item)
                for key, item in value.items()
                if key not in unsupported and key != "const"
            }
            if "const" in value:
                cleaned["enum"] = [value["const"]]
            if "enum" in cleaned and "type" not in cleaned and cleaned["enum"]:
                inferred_type = json_type(cleaned["enum"][0])
                if inferred_type:
                    cleaned["type"] = inferred_type
            schema_type = cleaned.get("type")
            if isinstance(schema_type, list) and "null" in schema_type:
                non_null_types = [item for item in schema_type if item != "null"]
                if len(non_null_types) == 1:
                    cleaned["type"] = non_null_types[0]
                    cleaned["nullable"] = True
            return cleaned
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(schema)


class OllamaProvider:
    name = "local"

    def __init__(self, settings: Settings, model: str | None = None):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = model or settings.ollama_model

    def generate(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> ProviderResult:
        started = time.monotonic()
        response = request_json(
            "POST",
            f"{self.base_url}/api/chat",
            payload={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0, "num_predict": 7000},
                "keep_alive": "10m",
            },
            timeout=1500,
        )
        content = response["message"]["content"]
        return ProviderResult(
            provider=self.name,
            model=self.model,
            content=content,
            parsed=_parse_json_content(content),
            elapsed_seconds=round(time.monotonic() - started, 2),
            usage={
                "input_tokens": response.get("prompt_eval_count"),
                "output_tokens": response.get("eval_count"),
            },
        )

    def healthcheck(self) -> dict[str, Any]:
        response = request_json("GET", f"{self.base_url}/api/tags", timeout=10)
        names = [item.get("name") for item in response.get("models", [])]
        return {
            "ok": self.model in names,
            "provider": self.name,
            "model": self.model,
            "model_available": self.model in names,
        }


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings, model: str | None = None):
        settings.validate_provider("gemini")
        self.base_url = settings.gemini_base_url.rstrip("/")
        self.api_key = settings.gemini_api_key
        self.model = model or settings.gemini_model

    def generate(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> ProviderResult:
        started = time.monotonic()
        model = quote(self.model, safe="-._")
        response = request_json(
            "POST",
            f"{self.base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 7000,
                    "responseMimeType": "application/json",
                    "responseSchema": _gemini_schema(schema),
                },
            },
            timeout=300,
        )
        parts = response["candidates"][0]["content"]["parts"]
        content = "".join(part.get("text", "") for part in parts)
        usage = response.get("usageMetadata", {})
        return ProviderResult(
            provider=self.name,
            model=self.model,
            content=content,
            parsed=_parse_json_content(content),
            elapsed_seconds=round(time.monotonic() - started, 2),
            usage={
                "input_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            },
        )

    def healthcheck(self) -> dict[str, Any]:
        result = self.generate(
            "Return only valid JSON matching the schema.",
            "Return an object where ok is true.",
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        )
        return {
            "ok": result.parsed.get("ok") is True,
            "provider": self.name,
            "model": self.model,
            "elapsed_seconds": result.elapsed_seconds,
        }

    def research(self, query: str) -> ResearchResult:
        started = time.monotonic()
        model = quote(self.model, safe="-._")
        response = request_json(
            "POST",
            f"{self.base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    "ابحث عن معلومات حديثة وموثوقة للطلب التالي. "
                                    "اذكر السنة، ولا تستخدم أرقامًا بلا مصدر، واكتب خلاصة عربية "
                                    "موجزة تصلح لتغذية نموذج آخر:\n\n" + query
                                )
                            }
                        ],
                    }
                ],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2500},
            },
            timeout=180,
        )
        candidate = response["candidates"][0]
        content = "".join(
            part.get("text", "") for part in candidate["content"].get("parts", [])
        )
        chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
        sources = []
        for chunk in chunks:
            web = chunk.get("web") or {}
            if web.get("uri"):
                sources.append(
                    {"title": web.get("title", "مصدر"), "url": web["uri"]}
                )
        unique_sources = list({source["url"]: source for source in sources}.values())
        usage = response.get("usageMetadata", {})
        return ResearchResult(
            content=content,
            sources=unique_sources,
            model=self.model,
            elapsed_seconds=round(time.monotonic() - started, 2),
            usage={
                "input_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            },
        )


def create_provider(
    name: str, settings: Settings, model: str | None = None
) -> Provider:
    settings.validate_provider(name)
    if name == "local":
        return OllamaProvider(settings, model)
    return GeminiProvider(settings, model)


def generate_with_fallback(
    *,
    settings: Settings,
    primary: str,
    fallback: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    model_override: str | None = None,
) -> tuple[ProviderResult, bool, str | None]:
    try:
        result = create_provider(primary, settings, model_override).generate(
            system, user, schema
        )
        return result, False, None
    except Exception as primary_error:
        if not fallback or fallback == primary:
            raise
        result = create_provider(fallback, settings).generate(system, user, schema)
        return result, True, str(primary_error)[:500]
