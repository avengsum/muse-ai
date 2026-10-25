import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai.types.responses import ResponseTextDeltaEvent

from app import ai_service


class FakeClient:
    async def close(self):
        return None


class FakeStreamResult:
    def __init__(self):
        self.final_output = "Hello world"
        self.is_complete = False

    async def stream_events(self):
        for sequence_number, delta in enumerate(["Hello ", "world"], start=1):
            yield SimpleNamespace(
                type="raw_response_event",
                data=ResponseTextDeltaEvent(
                    type="response.output_text.delta",
                    item_id="message-1",
                    output_index=0,
                    content_index=0,
                    delta=delta,
                    sequence_number=sequence_number,
                    logprobs=[],
                ),
            )

        self.is_complete = True

    def cancel(self):
        self.is_complete = True


class FakeRunner:
    @staticmethod
    def run_streamed(*args, **kwargs):
        return FakeStreamResult()


def fake_agent_runtime(messages, *args, **kwargs):
    context = ai_service.AgentRuntimeContext(
        messages=messages,
        timezone="UTC",
    )
    return object(), context, FakeClient()


class StreamingTests(unittest.TestCase):
    def test_stream_reply_forwards_model_deltas(self):
        async def collect_events():
            return [
                event
                async for event in ai_service.stream_reply(
                    [{"role": "user", "content": "Say hello"}],
                    None,
                    "UTC",
                    None,
                    None,
                )
            ]

        with (
            patch.object(ai_service, "Runner", FakeRunner),
            patch.object(ai_service, "create_agent_runtime", fake_agent_runtime),
        ):
            events = asyncio.run(collect_events())

        self.assertEqual(events[0], "Hello ")
        self.assertEqual(events[1], "world")
        self.assertEqual(events[2]['type'], 'agent_final')
        self.assertEqual(events[2]['output'], 'Hello world')

if __name__ == "__main__":
    unittest.main()
