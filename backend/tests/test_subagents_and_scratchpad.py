import unittest
from types import SimpleNamespace

from agents import Agent, function_tool

from app.scratchpad import ScratchpadState, update_scratchpad, update_scratchpad_fn
from app.subagents import (
    SPECIALIST_REGISTRY,
    SpecialistAgentSpec,
    build_agent_system,
    register_specialist,
)


@function_tool
def dummy_tool() -> str:
    return "dummy result"


class ScratchpadTests(unittest.TestCase):
    def test_scratchpad_summary_empty(self):
        state = ScratchpadState()
        self.assertEqual(state.summary(), "Scratchpad is empty.")

    def test_scratchpad_summary_with_plan_and_notes(self):
        state = ScratchpadState(
            plan=["Step 1: Search", "Step 2: Compare", "Step 3: Order"],
            current_step=1,
            notes="Found restaurant A (₹300) and B (₹250).",
        )
        summary = state.summary()
        self.assertIn("[x] Step 1: Step 1: Search", summary)
        self.assertIn("--> Step 2: Step 2: Compare", summary)
        self.assertIn("[ ] Step 3: Step 3: Order", summary)
        self.assertIn("Notes / Intermediate Findings:", summary)
        self.assertIn("Found restaurant A", summary)

    def test_update_scratchpad_tool(self):
        events = []
        context_obj = SimpleNamespace(
            scratchpad=ScratchpadState(),
            event_sink=lambda ev: events.append(ev),
        )
        wrapper = SimpleNamespace(context=context_obj)

        result = update_scratchpad_fn(
            wrapper,
            plan=["Analyze menu", "Check budget", "Confirm cart"],
            current_step_index=1,
            notes="Item 1 is within cap.",
        )

        self.assertIn("Scratchpad updated", result)
        self.assertIn("Step 2 of 3", result)
        self.assertEqual(context_obj.scratchpad.current_step, 1)
        self.assertEqual(context_obj.scratchpad.notes, "Item 1 is within cap.")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "scratchpad_updated")
        self.assertEqual(events[0]["current_step"], 1)

        # Also verify the FunctionTool wrapper is configured properly
        self.assertEqual(update_scratchpad.name, "update_scratchpad")

    def test_update_scratchpad_handles_empty(self):
        context_obj = SimpleNamespace(scratchpad=ScratchpadState())
        wrapper = SimpleNamespace(context=context_obj)
        result = update_scratchpad_fn(wrapper, plan=[])
        self.assertIn("Plan cannot be empty", result)


class SubAgentDelegationTests(unittest.TestCase):
    def test_specialist_registry_contains_core_domains(self):
        keys = {spec.key for spec in SPECIALIST_REGISTRY}
        self.assertIn("food", keys)
        self.assertIn("browser", keys)

    def test_dynamic_extensibility_adding_new_agent(self):
        """Verify that registering a new custom specialist agent works seamlessly."""
        custom_spec = SpecialistAgentSpec(
            name="Flight Booking Specialist",
            key="flight",
            handoff_description="Transfer to Flight Specialist for flights and tickets.",
            instructions_builder=lambda ctx: "You are the Flight Specialist.",
            tools_builder=lambda ctx: [dummy_tool],
            is_available=lambda ctx: True,
        )

        register_specialist(custom_spec)
        self.assertIn("flight", {spec.key for spec in SPECIALIST_REGISTRY})

        # Build agent system with supervisor and new specialist
        supervisor = Agent(name="Cooper", instructions="Supervisor instructions.")
        context = SimpleNamespace(timezone="UTC", browser_handler=None, swiggy_access_token=None)

        supervisor, specialists = build_agent_system(
            supervisor_agent=supervisor,
            context=context,
            model=None,
        )

        # Supervisor must have handoff to the new flight specialist
        self.assertIn("flight", specialists)
        flight_agent = specialists["flight"]
        self.assertEqual(flight_agent.name, "Flight Booking Specialist")

        # Flight agent must have handoff back to the supervisor
        self.assertEqual(len(flight_agent.handoffs), 1)
        self.assertEqual(flight_agent.handoffs[0].tool_name, "transfer_to_supervisor")


if __name__ == "__main__":
    unittest.main()
