"""Verification script for Milestone 2: Structured recommendation and lifecycle."""

import asyncio
import os
import pathlib
import sys
import uuid

STUDY_NAV_PATH = pathlib.Path("C:/Users/cath5/study-navigator")
sys.path.insert(0, str(STUDY_NAV_PATH))

from dotenv import load_dotenv
load_dotenv(STUDY_NAV_PATH / "study_agent" / ".env", override=True)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from study_agent.agent import root_agent


async def send_with_retry(runner: Runner, user_id: str, session_id: str, message: types.Content, max_retries: int = 5):
    for attempt in range(1, max_retries + 1):
        events = []
        try:
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
                events.append(event)
            return events
        except Exception as e:
            err_msg = str(e)
            if any(k in err_msg for k in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"]):
                print(f"  [Attempt {attempt}/{max_retries}] Transient spike ({err_msg[:60]}...); waiting 20s...")
                await asyncio.sleep(20)
            else:
                raise
    raise RuntimeError("Failed after max retries.")


async def test_scenario(scenario_name: str, checkin_text: str):
    service = InMemorySessionService()
    session_id = f"m2_{uuid.uuid4().hex[:8]}"
    session = await service.create_session(app_name="study_navigator", user_id="student_m2", session_id=session_id)
    runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

    events = await send_with_retry(
        runner, "student_m2", session.id, types.Content(role="user", parts=[types.Part(text=checkin_text)])
    )

    response_text = ""
    tools_called = []
    for event in events:
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    response_text += p.text + "\n"
                if p.function_call:
                    tools_called.append(p.function_call.name)

    state = dict((await service.get_session(app_name="study_navigator", user_id="student_m2", session_id=session.id)).state)

    has_proposal_header = "### Proposed Intervention:" in response_text
    has_target = "**Target**:" in response_text
    has_scope = "**Proposed Task & Scope**:" in response_text
    has_steps = "**Actionable Steps**:" in response_text
    has_confirmation_req = "**User Confirmation Required**:" in response_text
    has_metrics_tool = "calculate_study_metrics" in tools_called
    no_premature_action = "apply_study_intervention" not in tools_called

    pending_proposal = state.get("pending_proposal")
    slice_stage = state.get("slice_stage")
    proposal_details = state.get("proposal_details", {})
    has_target_in_state = bool(proposal_details.get("target"))
    has_scope_in_state = bool(proposal_details.get("scope"))

    passed = (
        has_proposal_header
        and has_target
        and has_scope
        and has_steps
        and has_confirmation_req
        and has_metrics_tool
        and no_premature_action
        and slice_stage == "awaiting_confirmation"
        and bool(pending_proposal)
        and has_target_in_state
        and has_scope_in_state
    )

    return {
        "scenario": scenario_name,
        "intervention": pending_proposal,
        "target": proposal_details.get("target"),
        "scope": proposal_details.get("scope"),
        "slice_stage": slice_stage,
        "tools_called": tools_called,
        "passed": passed,
    }


async def main():
    print("Running Milestone 2 verification (Structured Recommendation & Lifecycle)...")

    scenarios = [
        (
            "Scenario 1: SWITCH (Side-project check-in while high-stakes coursework due)",
            "I planned a 2-hour block for my personal portfolio project, but checking in to see if I should adjust my focus."
        ),
        (
            "Scenario 2: REST (Severe fatigue during study block)",
            "I am 30 minutes into studying DB, but I have a splitting headache, zero energy, and can barely keep my eyes open."
        ),
        (
            "Scenario 3: DIAGNOSE (Blocked conceptual understanding)",
            "I've spent an hour on Question 2 of AI Coursework 1 and I am completely stuck because I don't understand the A* heuristic from Lecture 5."
        ),
        (
            "Scenario 4: CONTINUE (Smooth progress on nearest high-priority task)",
            "I have been working on Question 1 of AI Coursework 1 for 45 minutes, finished the search algorithm implementation, feeling energetic and ready for the next section."
        )
    ]

    all_passed = True
    for name, prompt in scenarios:
        print(f"\n--- {name} ---")
        res = await test_scenario(name, prompt)
        print(f"Intervention: {res['intervention']}")
        print(f"Target:       {res['target']}")
        print(f"Scope:        {res['scope']}")
        print(f"Stage:        {res['slice_stage']}")
        print(f"Tools Called: {res['tools_called']}")
        print(f"Passed:       {res['passed']}")
        if not res['passed']:
            all_passed = False
        await asyncio.sleep(4)

    print(f"\nOverall Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")


if __name__ == "__main__":
    asyncio.run(main())
