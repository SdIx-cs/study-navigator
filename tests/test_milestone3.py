"""Verification suite for Milestone 3: Confirmation-Gated Action Tool and Human Approval Boundary."""

import asyncio
import os
import pathlib
import sys
import unittest
import uuid

STUDY_NAV_PATH = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_NAV_PATH))

from dotenv import load_dotenv
load_dotenv(STUDY_NAV_PATH / "study_agent" / ".env", override=True)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from study_agent.agent import root_agent


async def _run_with_retry(runner: Runner, user_id: str, session_id: str, message: types.Content, max_retries: int = 5):
    for attempt in range(1, max_retries + 1):
        events = []
        try:
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
                events.append(event)
            return events
        except Exception as e:
            err = str(e)
            if any(k in err for k in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"]):
                print(f"  [Attempt {attempt}/{max_retries}] API busy: {err[:60]}... waiting 20s...")
                await asyncio.sleep(20)
            else:
                raise
    raise RuntimeError(f"Failed after {max_retries} attempts.")


class TestMilestone3ApprovalBoundary(unittest.IsolatedAsyncioTestCase):
    """Verifies that human approval protects state-changing operations under all conditions."""

    async def test_scenario_1_full_confirmation_flow(self):
        """Scenario 1: User check-in -> Agent proposes SWITCH -> User confirms -> Gate approves -> Applied."""
        service = InMemorySessionService()
        session_id = f"m3_s1_{uuid.uuid4().hex[:8]}"
        session = await service.create_session(app_name="study_navigator", user_id="s1_user", session_id=session_id)
        runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

        # Turn 1: Check-in
        t1_prompt = "I planned a 2-hour study block for my personal side-project, but checking in to see if I should adjust my focus."
        tools_t1 = []
        events_t1 = await _run_with_retry(runner, "s1_user", session.id, types.Content(role="user", parts=[types.Part(text=t1_prompt)]))
        for ev in events_t1:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_call:
                        tools_t1.append(p.function_call.name)

        state_t1 = dict((await service.get_session(app_name="study_navigator", user_id="s1_user", session_id=session.id)).state)

        # Safety assertion: Action tool must NEVER be called prematurely on initial check-in
        self.assertNotIn("apply_study_intervention", tools_t1)
        self.assertEqual(state_t1.get("slice_stage"), "awaiting_confirmation")
        self.assertIn(state_t1.get("pending_proposal"), ["SWITCH", "SHRINK"])

        await asyncio.sleep(3)

        # Turn 2: User confirms proposal
        t2_prompt = "Yes, I confirm. Please apply this intervention to AI Coursework 1."
        confirmation_event = None
        events_t2 = await _run_with_retry(runner, "s1_user", session.id, types.Content(role="user", parts=[types.Part(text=t2_prompt)]))
        for ev in events_t2:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_call and p.function_call.name == "adk_request_confirmation":
                        confirmation_event = p.function_call

        # Gate assertion: Framework must intercept the tool call with adk_request_confirmation
        self.assertIsNotNone(confirmation_event, "ADK confirmation gate did not intercept tool call")

        await asyncio.sleep(3)

        # Turn 3: Human Gate approves (confirmed=True)
        call_id = confirmation_event.id
        resp_part = types.Part(function_response=types.FunctionResponse(name="adk_request_confirmation", id=call_id, response={"confirmed": True}))
        events_t3 = await _run_with_retry(runner, "s1_user", session.id, types.Content(role="user", parts=[resp_part]))

        tool_applied = False
        for ev in events_t3:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_response and p.function_response.name == "apply_study_intervention":
                        if p.function_response.response.get("status") == "applied":
                            tool_applied = True

        final_state = dict((await service.get_session(app_name="study_navigator", user_id="s1_user", session_id=session.id)).state)

        self.assertTrue(tool_applied)
        self.assertEqual(final_state.get("slice_stage"), "confirmed")
        self.assertEqual(final_state.get("approval_status"), "approved")
        self.assertIsNotNone(final_state.get("active_intervention"))

    async def test_scenario_2_dialogue_rejection_flow(self):
        """Scenario 2: User check-in -> Agent proposes REST -> User explicitly rejects -> Tool NOT called."""
        service = InMemorySessionService()
        session_id = f"m3_s2_{uuid.uuid4().hex[:8]}"
        session = await service.create_session(app_name="study_navigator", user_id="s2_user", session_id=session_id)
        runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

        # Turn 1: Check-in with exhaustion
        t1_prompt = "I am 30 minutes into a DB study block, but I have a splitting headache, zero energy, and blurred vision."
        await _run_with_retry(runner, "s2_user", session.id, types.Content(role="user", parts=[types.Part(text=t1_prompt)]))

        state_t1 = dict((await service.get_session(app_name="study_navigator", user_id="s2_user", session_id=session.id)).state)
        self.assertEqual(state_t1.get("pending_proposal"), "REST")

        await asyncio.sleep(3)

        # Turn 2: User explicitly rejects
        t2_prompt = "No, I reject this proposal. I do not want to rest. I will continue studying DB."
        tools_t2 = []
        events_t2 = await _run_with_retry(runner, "s2_user", session.id, types.Content(role="user", parts=[types.Part(text=t2_prompt)]))
        for ev in events_t2:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_call:
                        tools_t2.append(p.function_call.name)

        final_state = dict((await service.get_session(app_name="study_navigator", user_id="s2_user", session_id=session.id)).state)

        # Safety assertion: Rejection leaves plan unchanged; action tool was never called
        self.assertNotIn("apply_study_intervention", tools_t2)
        self.assertIsNone(final_state.get("active_intervention"))

    async def test_scenario_3_gate_rejection_flow(self):
        """Scenario 3: Agent calls tool -> Human Gate explicitly rejects (confirmed=False) -> Execution blocked."""
        service = InMemorySessionService()
        session_id = f"m3_s3_{uuid.uuid4().hex[:8]}"
        session = await service.create_session(app_name="study_navigator", user_id="s3_user", session_id=session_id)
        runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

        prompt = "I confirm and approve: please call apply_study_intervention to switch to AI cw1 immediately."
        confirmation_event = None
        events = await _run_with_retry(runner, "s3_user", session.id, types.Content(role="user", parts=[types.Part(text=prompt)]))
        for ev in events:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_call and p.function_call.name == "adk_request_confirmation":
                        confirmation_event = p.function_call

        self.assertIsNotNone(confirmation_event, "Expected gate to intercept action tool")

        await asyncio.sleep(3)

        # Human Gate explicitly denies (confirmed=False)
        call_id = confirmation_event.id
        resp_part = types.Part(function_response=types.FunctionResponse(name="adk_request_confirmation", id=call_id, response={"confirmed": False}))
        events_reject = await _run_with_retry(runner, "s3_user", session.id, types.Content(role="user", parts=[resp_part]))

        tool_applied = False
        tool_rejected_by_gate = False
        for ev in events_reject:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_response and p.function_response.name == "apply_study_intervention":
                        resp_dict = p.function_response.response or {}
                        if resp_dict.get("status") == "applied":
                            tool_applied = True
                        if resp_dict.get("error") == "This tool call is rejected.":
                            tool_rejected_by_gate = True

        final_state = dict((await service.get_session(app_name="study_navigator", user_id="s3_user", session_id=session.id)).state)

        # Safety assertion: Execution blocked, plan unchanged
        self.assertFalse(tool_applied)
        self.assertTrue(tool_rejected_by_gate)
        self.assertIsNone(final_state.get("active_intervention"))
        self.assertEqual(final_state.get("approval_status"), "rejected")

    async def test_scenario_4_modification_flow(self):
        """Scenario 4: User modifies proposal (DIAGNOSE -> SHRINK) -> Gate approves -> Applied with modified details."""
        service = InMemorySessionService()
        session_id = f"m3_s4_{uuid.uuid4().hex[:8]}"
        session = await service.create_session(app_name="study_navigator", user_id="s4_user", session_id=session_id)
        runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

        # Turn 1: Check-in
        t1_prompt = "Checking in: I've been trying to solve Question 2 on AI Coursework 1 for over an hour, but I don't understand heuristics from lecture 5."
        await _run_with_retry(runner, "s4_user", session.id, types.Content(role="user", parts=[types.Part(text=t1_prompt)]))

        await asyncio.sleep(3)

        # Turn 2: User modifies proposal to SHRINK to 30 mins
        t2_prompt = "I want to modify the proposal: let's SHRINK the session to 30 minutes of reviewing lecture 5 slides only. Please apply this modified intervention."
        confirmation_event = None
        events_t2 = await _run_with_retry(runner, "s4_user", session.id, types.Content(role="user", parts=[types.Part(text=t2_prompt)]))
        for ev in events_t2:
            if ev.content and ev.content.parts:
                for p in ev.content.parts:
                    if p.function_call and p.function_call.name == "adk_request_confirmation":
                        confirmation_event = p.function_call

        self.assertIsNotNone(confirmation_event, "Gate should intercept modified intervention tool call")

        await asyncio.sleep(3)

        # Gate approves modified intervention
        call_id = confirmation_event.id
        resp_part = types.Part(function_response=types.FunctionResponse(name="adk_request_confirmation", id=call_id, response={"confirmed": True}))
        await _run_with_retry(runner, "s4_user", session.id, types.Content(role="user", parts=[resp_part]))

        final_state = dict((await service.get_session(app_name="study_navigator", user_id="s4_user", session_id=session.id)).state)

        # Safety assertion: Only the modified action took effect
        self.assertEqual(final_state.get("slice_stage"), "confirmed")
        self.assertEqual(final_state.get("approval_status"), "approved")
        active = final_state.get("active_intervention") or {}
        self.assertEqual(active.get("intervention"), "SHRINK")


if __name__ == "__main__":
    unittest.main()
