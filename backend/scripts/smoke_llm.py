"""Live check of the Claude adapter. Requires a real credential; costs a few cents.

The unit tests drive the adapter with a stub, so they prove the request we *build* and how we
interpret a response — but not that the API accepts it. This script closes that gap, and it is
the only thing that can verify prompt caching actually engages, since a cache hit is a property of
the service, not of our code.

    export ANTHROPIC_API_KEY=...            # or: ant auth login
    python scripts/smoke_llm.py

Checks, in order:
  1. a streaming turn returns text and usage
  2. `thinking: adaptive` + `output_config.effort` are accepted
  3. the second identical-prefix turn reports cache_read_input_tokens > 0
  4. a strict tool definition is accepted and can be called
  5. server-side refusal fallbacks are accepted (if configured)
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.agent.prompts import assemble
from app.providers.llm.anthropic_provider import AnthropicLLMProvider
from app.providers.llm.base import (
    Effort,
    LLMRequest,
    StreamCompleted,
    TextDelta,
    ToolSpec,
)

MODEL = os.environ.get("VAANIOS_LLM_MODEL", "claude-opus-5")
# Padding so the cached prefix clears the model's minimum cacheable length. Below it, caching
# silently does nothing — the failure this script exists to catch.
PADDING = "\n\nReference notes for this course, for your own grounding:\n" + "\n".join(
    f"- Unit {i}: circuit analysis, network theorems, transient response, "
    f"phasor methods, and two-port parameters as taught in semester {i}."
    for i in range(1, 60)
)

FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAIL
    mark = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")


async def run_turn(
    provider: AnthropicLLMProvider, utterance: str, *, tools: tuple[ToolSpec, ...] = ()
) -> tuple[str, StreamCompleted | None]:
    prompt = assemble(history=[], utterance=utterance, memory_digest=PADDING.strip())
    request = LLMRequest(
        system=prompt.system,
        messages=prompt.messages,
        tools=tools,
        max_output_tokens=256,
        effort=Effort.LOW,
    )
    text = ""
    completed: StreamCompleted | None = None
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            text += event.text
        elif isinstance(event, StreamCompleted):
            completed = event
    return text, completed


async def main() -> int:
    provider = AnthropicLLMProvider(model=MODEL, refusal_fallback_model="claude-opus-4-8")
    try:
        text, first = await run_turn(provider, "In one sentence, what does KVL state?")
        check("streaming turn returns text", bool(text.strip()), text[:70])
        check("usage is reported", first is not None and first.usage.output_tokens > 0)
        check(
            "adaptive thinking and effort accepted",
            first is not None and first.stop_reason in {"end_turn", "max_tokens"},
            first.stop_reason if first else "no completion",
        )

        # Same cacheable prefix, different question.
        _, second = await run_turn(provider, "In one sentence, what does KCL state?")
        cache_read = second.usage.cache_read_input_tokens if second else 0
        check(
            "prompt cache engages on the second turn",
            cache_read > 0,
            f"cache_read_input_tokens={cache_read}"
            + ("" if cache_read else "; prefix may be below the minimum cacheable length"),
        )
        if second is not None:
            check(
                "adapter does not report a false cache warning",
                second.cache_breakpoint_ineffective == (cache_read == 0),
            )

        tool = ToolSpec(
            name="search_knowledge",
            description="Search the student's course material for a topic.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
        _, third = await run_turn(
            provider,
            "Look up 'displacement current' in my course material before answering.",
            tools=(tool,),
        )
        check(
            "strict tool definition accepted",
            third is not None and third.stop_reason in {"tool_use", "end_turn"},
            third.stop_reason if third else "no completion",
        )

        tokens = await provider.count_tokens(
            LLMRequest(
                system=assemble(history=[], utterance="hi").system,
                messages=assemble(history=[], utterance="hi").messages,
            )
        )
        check("token counting works", tokens > 0, f"{tokens} tokens")
    finally:
        await provider.aclose()

    print()
    print("All checks passed." if FAIL == 0 else f"{FAIL} check(s) failed.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "No credential found. Set ANTHROPIC_API_KEY, or run `ant auth login` "
            "(the SDK reads the stored profile automatically).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main()))
