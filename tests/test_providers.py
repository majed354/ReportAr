import json
import unittest
from unittest.mock import patch

from report_worker.config import Settings
from report_worker.providers import GeminiProvider, OllamaProvider, generate_with_fallback


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

    @patch("report_worker.providers.request_json")
    def test_ollama_uses_structured_format(self, request):
        request.return_value = {
            "message": {"content": '{"ok": true}'},
            "eval_count": 3,
        }
        result = OllamaProvider(Settings(), "gemma-test").generate(
            "system", "user", self.schema
        )
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["format"], self.schema)
        self.assertEqual(result.parsed, {"ok": True})

    @patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"})
    @patch("report_worker.providers.request_json")
    def test_gemini_key_is_header_only(self, request):
        request.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
            "usageMetadata": {"totalTokenCount": 4},
        }
        provider = GeminiProvider(Settings(), "gemini-test")
        result = provider.generate("system", "user", self.schema)
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "secret-test-key")
        self.assertNotIn("secret-test-key", json.dumps(kwargs["payload"]))
        self.assertEqual(
            kwargs["payload"]["generationConfig"]["responseMimeType"],
            "application/json",
        )
        self.assertEqual(result.parsed, {"ok": True})

    @patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"})
    @patch("report_worker.providers.request_json")
    def test_gemini_removes_unsupported_schema_fields_recursively(self, request):
        request.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"items": []}'}]}}],
        }
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"const": "1.0"},
                "optional_number": {"type": ["number", "null"]},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
        }
        GeminiProvider(Settings(), "gemini-test").generate("system", "user", schema)
        response_schema = request.call_args.kwargs["payload"]["generationConfig"][
            "responseSchema"
        ]
        self.assertNotIn("$schema", response_schema)
        self.assertNotIn("additionalProperties", json.dumps(response_schema))
        self.assertEqual(
            response_schema["properties"]["version"],
            {"enum": ["1.0"], "type": "string"},
        )
        self.assertEqual(
            response_schema["properties"]["optional_number"],
            {"type": "number", "nullable": True},
        )

    @patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"})
    @patch("report_worker.providers.request_json")
    def test_gemini_research_uses_google_search_and_returns_sources(self, request):
        request.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "خلاصة موثقة"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "المصدر", "uri": "https://example.com"}}
                        ]
                    },
                }
            ],
            "usageMetadata": {},
        }
        result = GeminiProvider(Settings(), "gemini-test").research("ابحث عن إحصائية")
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"], [{"google_search": {}}])
        self.assertEqual(result.sources[0]["url"], "https://example.com")

    @patch("report_worker.providers.create_provider")
    def test_fallback_is_used_after_primary_failure(self, create):
        primary = create.return_value
        primary.generate.side_effect = [RuntimeError("offline"), unittest.mock.DEFAULT]
        primary.generate.return_value.parsed = {"ok": True}
        primary.generate.return_value.provider = "gemini"
        result, used, error = generate_with_fallback(
            settings=Settings(),
            primary="local",
            fallback="gemini",
            system="system",
            user="user",
            schema=self.schema,
        )
        self.assertTrue(used)
        self.assertIn("offline", error)
        self.assertEqual(result.parsed, {"ok": True})


if __name__ == "__main__":
    unittest.main()
