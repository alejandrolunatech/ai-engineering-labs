"""Run one review and record runtime + usage.

Usage (from labs/01-pr-guardian):
    python -m src.pr_guardian.review <case_id>
"""

import asyncio
import json
import sys
import time

from agents import Runner, ToolCallItem, trace
from dotenv import load_dotenv

from .agent import build_agent
from .models import ReviewResult, ReviewRun, ToolCallRecord, UsageStats
from .tools import ReviewContext, resolve_case_dir

MAX_TURNS = 12


def _tool_calls(items) -> list[ToolCallRecord]:
    records = []
    for item in items:
        if not isinstance(item, ToolCallItem):
            continue
        raw = item.raw_item
        arguments = raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            parsed = {"_unparsed": arguments}
        records.append(ToolCallRecord(name=item.tool_name or "unknown", arguments=parsed))
    return records


async def review_case(case_id: str, model: str | None = None) -> ReviewRun:
    resolve_case_dir(case_id)  # fail fast (and free) on a bad case_id
    agent = build_agent(model)

    start = time.perf_counter()
    with trace("PR Guardian review", metadata={"case_id": case_id}) as t:
        result = await Runner.run(
            agent,
            input=f"Review the pull request for case_id={case_id!r}.",
            context=ReviewContext(case_id=case_id),
            max_turns=MAX_TURNS,
        )
    elapsed = time.perf_counter() - start

    usage = result.context_wrapper.usage
    return ReviewRun(
        case_id=case_id,
        model=str(agent.model),
        elapsed_seconds=round(elapsed, 3),
        usage=UsageStats(
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        ),
        trace_id=t.trace_id,
        tool_calls=_tool_calls(result.new_items),
        result=result.final_output_as(ReviewResult, raise_if_incorrect_type=True),
    )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m src.pr_guardian.review <case_id>")
    load_dotenv()
    run = asyncio.run(review_case(sys.argv[1]))
    print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
