import asyncio
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from server.server import ChatRequest, Message, _clean_answer, app, chat, health, models


class ModelApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.state.pipeline = None
        app.state.tokenizer = None
        app.state.generation_lock = None

    def test_reasoning_wrapper_is_removed(self) -> None:
        self.assertEqual(_clean_answer("<think>private</think>Public answer"), "Public answer")
        self.assertEqual(_clean_answer("Public answer"), "Public answer")

    def test_request_bounds_prevent_uncontrolled_generation(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(
                messages=[Message(role="user", content="question")],
                max_tokens=4097,
            )

    def test_routes_report_model_identity_and_not_ready_state(self) -> None:
        model_list = asyncio.run(models())
        self.assertTrue(model_list["data"][0]["id"])
        with self.assertRaises(HTTPException) as health_error:
            asyncio.run(health())
        with self.assertRaises(HTTPException) as chat_error:
            asyncio.run(
                chat(ChatRequest(messages=[Message(role="user", content="question")]))
            )
        self.assertEqual(health_error.exception.status_code, 503)
        self.assertEqual(chat_error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()