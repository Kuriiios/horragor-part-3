import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.API.api_schemas import ChatRequest
from src.API.main_api import process_chat_message
from src.graph.tools_nodes import _execute_tool_call, _post_local_llm
from src.observability import get_langfuse_client, start_langfuse_chat_trace


class FakeGeneration:
	def __init__(self) -> None:
		self.updates: list[dict] = []

	def __enter__(self):
		return self

	def __exit__(self, *_) -> None:
		return None

	def update(self, **kwargs) -> None:
		self.updates.append(kwargs)


class LangfuseIntegrationTests(unittest.TestCase):
	def test_client_stays_disabled_without_credentials(self) -> None:
		with patch.dict(
			os.environ,
			{"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""},
		):
			self.assertIsNone(get_langfuse_client())

	def test_chat_trace_propagates_session_and_environment(self) -> None:
		client = Mock()
		trace = FakeGeneration()
		propagation = FakeGeneration()
		client.start_as_current_observation.return_value = trace
		with (
			patch("src.observability.get_langfuse_client", return_value=client),
			patch("langfuse.propagate_attributes", return_value=propagation) as propagate,
			patch.dict(os.environ, {"LANGFUSE_TRACING_ENVIRONMENT": "test"}),
			start_langfuse_chat_trace(
				question="Tell me about Test Film",
				session_id="chat-123",
				metadata={"feature": "horror-movie-chat"},
			) as current_trace,
		):
			self.assertIs(current_trace, trace)

		client.start_as_current_observation.assert_called_once_with(
			name="answer-chat-question",
			as_type="agent",
			input={"question": "Tell me about Test Film"},
			metadata={"feature": "horror-movie-chat"},
		)
		propagate.assert_called_once_with(
			trace_name="answer-chat-question",
			tags=["horragor", "chat"],
			session_id="chat-123",
			environment="test",
		)

	def test_chat_passes_langfuse_callback_to_graph(self) -> None:
		graph = Mock()
		graph.ainvoke = AsyncMock(
			return_value={
				"final_response": "A grounded answer.",
				"rag_results": [{"movie": {"title": "Test Film"}, "score": 1.0}],
				"metadata": {"top_score": 1.0, "route": "narration"},
				"token_usage": {
					"input": 30,
					"output": 10,
					"total": 40,
					"by_generation": {
						"generate-narration": {"input": 30, "output": 10, "total": 40},
					},
				},
			}
		)
		handler = object()
		with (
			patch("src.API.main_api.graph_app", graph),
			patch("src.API.main_api.create_langfuse_handler", return_value=handler),
		):
			response = asyncio.run(
				process_chat_message(
					ChatRequest(
						question="Tell me about Test Film",
						session_id="chat-123",
					)
				)
			)

		graph.ainvoke.assert_awaited_once()
		config = graph.ainvoke.await_args.kwargs["config"]
		self.assertEqual(config["callbacks"], [handler])
		self.assertEqual(config["run_name"], "run-movie-agent-graph")
		self.assertEqual(response.response, "A grounded answer.")
		if response.token_usage is None:
			self.fail("Expected token usage from the graph")
		self.assertEqual(response.token_usage.total, 40)
		self.assertEqual(response.token_usage.by_generation["generate-narration"].output, 10)

	def test_chat_creates_a_session_aware_root_trace(self) -> None:
		graph = Mock()
		graph.ainvoke = AsyncMock(
			return_value={
				"final_response": "A grounded answer.",
				"rag_results": [{"movie": {"title": "Test Film"}, "score": 1.0}],
				"metadata": {"top_score": 1.0, "route": "narration"},
			}
		)
		trace = FakeGeneration()
		with (
			patch("src.API.main_api.graph_app", graph),
			patch("src.API.main_api.create_langfuse_handler", return_value=None),
			patch(
				"src.API.main_api.start_langfuse_chat_trace",
				return_value=trace,
			) as start_trace,
		):
			asyncio.run(
				process_chat_message(
					ChatRequest(
						question="Tell me about Test Film",
						session_id="chat-123",
					)
				)
			)

		start_trace.assert_called_once_with(
			question="Tell me about Test Film",
			session_id="chat-123",
			metadata={"feature": "horror-movie-chat", "history_turns": 0},
		)
		self.assertEqual(trace.updates[0]["output"], "A grounded answer.")

	def test_local_llm_generation_records_openai_usage(self) -> None:
		generation = FakeGeneration()
		captured_usage: list[dict[str, int]] = []
		response = Mock()
		response.json.return_value = {
			"choices": [{"message": {"content": "Generated answer."}}],
			"usage": {
				"prompt_tokens": 12,
				"completion_tokens": 5,
				"total_tokens": 17,
			},
		}
		with (
			patch("src.graph.tools_nodes.start_langfuse_observation", return_value=generation),
			patch("src.graph.tools_nodes.requests.post", return_value=response),
		):
			result = _post_local_llm(
				[{"role": "user", "content": "Question"}],
				max_tokens=20,
				temperature=0.0,
				observation_name="test-generation",
				usage_callback=captured_usage.append,
			)

		self.assertEqual(result, "Generated answer.")
		self.assertEqual(
			generation.updates[0]["usage_details"],
			{"input": 12, "output": 5, "total": 17},
		)
		self.assertEqual(captured_usage, [{"input": 12, "output": 5, "total": 17}])

	def test_failed_tool_completes_observation_with_error_output(self) -> None:
		observation = FakeGeneration()
		with (
			patch(
				"src.graph.tools_nodes.start_langfuse_observation",
				return_value=observation,
			),
			patch(
				"src.graph.tools_nodes.calculate_movie_age",
				side_effect=ValueError("invalid year"),
			),
			patch("src.graph.tools_nodes.record_tool_call") as record_tool,
		):
			result = _execute_tool_call(
				{
					"name": "calculate_movie_age",
					"arguments": {"release_year": 1500},
				}
			)

		self.assertIsNone(result)
		self.assertEqual(observation.updates[0]["level"], "ERROR")
		self.assertEqual(observation.updates[0]["output"], {"error": "ValueError"})
		record_tool.assert_called_once_with("calculate_movie_age", "error")


if __name__ == "__main__":
	unittest.main()