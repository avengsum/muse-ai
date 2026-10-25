import time
from dataclasses import dataclass, field
from typing import Any

from agents import RunContextWrapper, function_tool


@dataclass
class ScratchpadState:
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    notes: str = ""
    updated_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        if not self.plan:
            return "Scratchpad is empty."
        lines = ["# Current Execution Plan:"]
        for idx, step in enumerate(self.plan):
            status = "CURRENT" if idx == self.current_step else ("DONE" if idx < self.current_step else "PENDING")
            marker = "-->" if idx == self.current_step else (" [x]" if idx < self.current_step else " [ ]")
            lines.append(f"{marker} Step {idx + 1}: {step}")
        if self.notes:
            lines.append(f"\nNotes / Intermediate Findings:\n{self.notes.strip()}")
        return "\n".join(lines)


def update_scratchpad_fn(
    context: RunContextWrapper[Any],
    plan: list[str],
    current_step_index: int = 0,
    notes: str | None = None,
) -> str:
    cleaned_plan = [str(step).strip() for step in plan if str(step).strip()]
    if not cleaned_plan:
        return "Plan cannot be empty. Please provide at least one milestone."

    clamped_index = max(0, min(current_step_index, len(cleaned_plan) - 1))
    current_step_desc = cleaned_plan[clamped_index]
    combined_notes = str(notes or "").strip()

    runtime_ctx = context.context
    if hasattr(runtime_ctx, "scratchpad"):
        runtime_ctx.scratchpad.plan = cleaned_plan
        runtime_ctx.scratchpad.current_step = clamped_index
        if combined_notes:
            runtime_ctx.scratchpad.notes = combined_notes
        runtime_ctx.scratchpad.updated_at = time.time()

    # Emit real-time status event to the streaming sink
    event_sink = getattr(runtime_ctx, "event_sink", None)
    if callable(event_sink):
        event_sink(
            {
                "type": "scratchpad_updated",
                "plan": cleaned_plan,
                "current_step": clamped_index,
                "current_step_text": current_step_desc,
                "notes": combined_notes,
                "message": f"Step {clamped_index + 1}/{len(cleaned_plan)}: {current_step_desc}",
            }
        )

    return (
        f"Scratchpad updated. Now focusing on Step {clamped_index + 1} of {len(cleaned_plan)}: "
        f"'{current_step_desc}'. Continue executing."
    )


update_scratchpad = function_tool(
    name_override="update_scratchpad",
    description_override=(
        "Create or update your multi-step execution plan and working notes. "
        "Call this at the start of complex, multi-turn, comparison, or multi-restaurant tasks "
        "to track progress and preserve findings across turns."
    ),
    use_docstring_info=False,
    strict_mode=False,
)(update_scratchpad_fn)
