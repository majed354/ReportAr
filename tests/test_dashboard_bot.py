import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import report_worker.dashboard as dashboard


class DashboardBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        dashboard.BOT_TASK = None
        dashboard.BOT_ERROR = ""

    @patch("report_worker.dashboard.TelegramReportBot")
    @patch("report_worker.dashboard.Bot")
    @patch.object(dashboard.VAULT, "load")
    async def test_start_bot_waits_until_polling_is_ready(self, load, bot_class, report_bot):
        load.return_value = {"telegram_bot_token": "test-token"}
        identity = MagicMock()
        identity.username = "report_test_bot"
        bot_class.return_value.get_me = AsyncMock(return_value=identity)

        async def run_async(ready):
            ready.set()
            await asyncio.Event().wait()

        report_bot.return_value.run_async = run_async
        result = await dashboard.start_bot()
        self.assertTrue(result["running"])
        self.assertEqual(result["username"], "report_test_bot")
        dashboard.BOT_TASK.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await dashboard.BOT_TASK

    @patch("report_worker.dashboard.request_json")
    @patch.object(dashboard.VAULT, "load")
    async def test_local_models_lists_gemma_and_qwen_chat_models_only(self, load, request):
        load.return_value = {"ollama_base_url": "http://127.0.0.1:11434"}
        request.return_value = {
            "models": [
                {"name": "gemma4:31b", "size": 19_000_000_000},
                {"name": "qwen3.6:35b", "size": 23_000_000_000},
                {"name": "qwen3-embedding:8b", "size": 4_700_000_000},
                {"name": "kimi-k2.5:cloud", "size": 0},
            ]
        }
        result = await dashboard.local_models()
        self.assertEqual(
            [model["name"] for model in result["models"]],
            ["gemma4:31b", "qwen3.6:35b"],
        )


if __name__ == "__main__":
    unittest.main()
