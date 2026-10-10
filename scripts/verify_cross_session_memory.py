import asyncio
import os
import pathlib
import sys
import uuid

# Ensure repository root is on sys.path
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from study_agent.agent import root_agent
from study_agent.db import clear_history, get_preferences, get_custom_tasks

async def run_demo():
    print("================================================================================")
    print("CROSS-SESSION MEMORY & WORKLOAD INTEGRATION DEMO")
    print("================================================================================")

    # Initialize fresh environment
    clear_history()
    service = InMemorySessionService()
    runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

    user_id = "student_john_demo"
    session_1_id = f"sess_1_{uuid.uuid4().hex[:6]}"
    session_2_id = f"sess_2_{uuid.uuid4().hex[:6]}"

    await service.create_session(app_name="study_navigator", user_id=user_id, session_id=session_1_id)
    await service.create_session(app_name="study_navigator", user_id=user_id, session_id=session_2_id)

    # --- SESSION 1: Profile & Custom Module Introduction ---
    prompt_1 = (
        "Hi! Call me John. Also, I take Computer Networks (CN) with Coursework 1 due in 5 days "
        "(15-10-2026) worth 20%. I prefer 30-minute blocks because of eye strain."
    )
    print(f"\n[SESSION 1] Student -> Agent: {prompt_1}\n")

    t1_response = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_1_id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt_1)]),
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    t1_response += p.text
                if p.function_call:
                    print(f"  [Tool Call] {p.function_call.name}({p.function_call.args})")

    print(f"\n[SESSION 1] Agent Response:\n{t1_response.strip()}\n")

    # Inspect persistent store
    print("--- SQLite Persistent Store Inspection ---")
    print(f"Stored Preferences: {get_preferences(user_id)}")
    print(f"Stored Custom Tasks: {get_custom_tasks(user_id)}")

    await asyncio.sleep(4)

    # --- SESSION 2: Brand New Session (Isolated History) ---
    prompt_2 = "Checking in: I have low energy today and some eye fatigue. What should I focus on?"
    print(f"\n================================================================================")
    print(f"[SESSION 2 (NEW SESSION ID)] Student -> Agent: {prompt_2}\n")

    t2_response = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_2_id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt_2)]),
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    t2_response += p.text
                if p.function_call:
                    print(f"  [Tool Call] {p.function_call.name}({p.function_call.args})")

    print(f"\n[SESSION 2] Agent Response:\n{t2_response.strip()}\n")
    print("================================================================================")

if __name__ == "__main__":
    asyncio.run(run_demo())
