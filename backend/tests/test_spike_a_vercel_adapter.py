"""Spike A: PydanticAI v2 VercelAIAdapter bridge verification (offline, no frontend).

Verified on installed pydantic-ai 2.43.0 (roadmap M0 Spike A):
1. import path: pydantic_ai.ui.vercel_ai.VercelAIAdapter + granular 3-method surface
2. AI SDK v5 UIMessage run-input parsing
3. offline end-to-end: Agent(TestModel()) -> adapter -> SSE frames
4. custom data part support: DataChunk(type="data-...") carries domain payloads

These assertions are the discovery record that M2's event-mapping contract
(design-architecture §2.4 / §3.2) builds on.
"""

import asyncio
import json

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.ui.vercel_ai import VercelAIAdapter


def _make_agent() -> Agent:
    def submit_plan(steps: list[dict]) -> str:
        """Submit the analysis plan."""
        return "plan accepted"

    return Agent(model=TestModel(), tools=[submit_plan])


def _make_adapter(agent: Agent) -> VercelAIAdapter:
    body = {
        "id": "m1",
        "trigger": "submit-message",
        "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
    }
    run_input = VercelAIAdapter.build_run_input(json.dumps(body).encode())
    return VercelAIAdapter(agent, run_input)


def test_adapter_granular_surface_exists():
    for name in ("build_run_input", "run_stream", "encode_stream"):
        assert hasattr(VercelAIAdapter, name), name


def test_run_input_parses_ai_sdk_v5_body():
    body = {
        "id": "m1",
        "trigger": "submit-message",
        "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
    }
    run_input = VercelAIAdapter.build_run_input(json.dumps(body).encode())
    assert type(run_input).__name__ == "SubmitMessage"
    assert run_input.messages[0].parts[0].type == "text"


def test_end_to_end_sse_stream_offline():
    adapter = _make_adapter(_make_agent())

    async def collect() -> list[str]:
        events = adapter.run_stream()
        return [frame async for frame in adapter.encode_stream(events)]

    frames = asyncio.run(collect())
    joined = "".join(frames)

    # tool path: TestModel auto-calls submit_plan; text path follows (design §2.4 mapping)
    for marker in (
        '"type":"start"',
        '"type":"tool-input-start"',
        '"type":"tool-input-delta"',
        '"type":"tool-input-available"',
        '"type":"tool-output-available"',
        '"type":"text-delta"',
        '"type":"finish"',
    ):
        assert marker in joined, marker
    assert frames[-1] == "data: [DONE]\n\n"


def test_custom_data_part_chunk():
    from pydantic_ai.ui.vercel_ai.response_types import DataChunk

    chunk = DataChunk(
        type="data-plan",
        id="plan-1",
        data={"steps": [{"id": "s1", "title": "load"}]},
    )
    assert chunk.type == "data-plan"
    assert chunk.data["steps"][0]["id"] == "s1"
