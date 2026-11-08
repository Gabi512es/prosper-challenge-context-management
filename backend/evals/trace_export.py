"""Export readable original transcripts and newly captured tool traces."""

import argparse
import asyncio
import json
from pathlib import Path

from .text_integration import run_dev_case


def _original_section(label: str, run: dict) -> list[str]:
    lines = [f"## {label} — original retained transcript", ""]
    for item in run["transcript"]:
        role = item["role"].capitalize()
        lines.extend((f"**{role}:** {item.get('text', '')}", ""))
        for tool in item.get("tools", []):
            lines.extend(
                (
                    f"- Tool call: `{tool}`",
                    "  - Arguments: *not retained by the original matrix run*",
                    "  - Result: *not retained by the original matrix run*",
                    "",
                )
            )
    return lines


def _captured_section(
    label: str,
    context: list[dict],
    error: str | None,
    *,
    suffix: str = "pre-fix reproduction with full tool trace",
) -> list[str]:
    lines = [f"## {label} — {suffix}", ""]
    if error:
        lines.extend((f"Run diagnostic: `{error}`", ""))
    for message in context:
        role = message.get("role")
        if role == "user":
            lines.extend((f"**Patient:** {message.get('content', '')}", ""))
        elif role == "assistant":
            if message.get("content"):
                lines.extend((f"**Agent:** {message['content']}", ""))
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                arguments = _json_pretty(function.get("arguments"))
                lines.extend(
                    (
                        f"- Tool call `{function.get('name')}` (`{call.get('id')}`)",
                        "",
                        "  Arguments:",
                        "",
                        "  ```json",
                        *[f"  {line}" for line in arguments.splitlines()],
                        "  ```",
                        "",
                    )
                )
        elif role == "developer":
            finished = _finished_tool_result(message.get("content"))
            if finished:
                tool_call_id, result = finished
                lines.extend(
                    (
                        f"- Tool result (`{tool_call_id}`):",
                        "",
                        "  ```json",
                        *[f"  {line}" for line in result.splitlines()],
                        "  ```",
                        "",
                    )
                )
    return lines


def _finished_tool_result(content) -> tuple[str, str] | None:
    if not isinstance(content, str):
        return None
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return None
    if value.get("type") != "async_tool" or value.get("status") != "finished":
        return None
    return value.get("tool_call_id", "unknown"), _json_pretty(value.get("result"))


def _json_pretty(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, indent=2, sort_keys=True)


async def export(args) -> None:
    report = json.loads(args.report.read_text())
    originals = {(run["scenario_id"], run["repetition"]): run for run in report["runs"]}
    selections = []
    for value in args.select:
        scenario_id, repetition = value.rsplit(":", 1)
        selections.append((scenario_id, int(repetition)))

    if args.saved_only:
        lines = [
            "# Selected development transcripts",
            "",
            "These are exact saved contexts from the selected matrix runs, including patient and "
            "agent messages plus every retained tool call and final tool result.",
            "",
        ]
        for scenario_id, repetition in selections:
            run = originals[(scenario_id, repetition)]
            label = f"{scenario_id} run {repetition}"
            lines.extend(
                _captured_section(
                    label,
                    run.get("context_messages", []),
                    run.get("error"),
                    suffix="saved matrix context with full tool trace",
                )
            )
        args.output.write_text("\n".join(lines).rstrip() + "\n")
        print(f"output={args.output}", flush=True)
        return

    lines = [
        "# Selected development transcripts",
        "",
        "The original matrix retained patient/agent text and tool names, but not tool arguments "
        "or returned payloads. Those missing payloads cannot be reconstructed from the metrics "
        "JSONL. Each original transcript is therefore followed by a clearly labeled pre-fix "
        "reproduction captured before scheduling behavior was changed.",
        "",
    ]
    for scenario_id, repetition in selections:
        label = f"{scenario_id} run {repetition}"
        lines.extend(_original_section(label, originals[(scenario_id, repetition)]))

    run_id = args.capture_run_id
    for index, (scenario_id, repetition) in enumerate(selections, start=1):
        captured = await run_dev_case(scenario_id, run_id=run_id)
        label = f"{scenario_id} reproduction {index} (requested run {repetition})"
        lines.extend(_captured_section(label, captured.context_messages, captured.error))
        print(f"captured {label}", flush=True)

    args.output.write_text("\n".join(lines).rstrip() + "\n")
    print(f"output={args.output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--select", nargs="+", required=True)
    parser.add_argument("--capture-run-id")
    parser.add_argument("--saved-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.saved_only and not args.capture_run_id:
        parser.error("--capture-run-id is required unless --saved-only is set")
    asyncio.run(export(args))


if __name__ == "__main__":
    main()
