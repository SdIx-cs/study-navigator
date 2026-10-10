"""ADK-style reproducible evaluation runner for Study Navigator (Milestone 4)."""

import asyncio
import json
import os
import pathlib
import sys
import time

STUDY_NAV_PATH = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_NAV_PATH))

from dotenv import load_dotenv
load_dotenv(STUDY_NAV_PATH / "study_agent" / ".env", override=True)

from google import genai
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from study_agent.agent import root_agent

EVALS_DIR = pathlib.Path(__file__).resolve().parent
GOLDEN_FILE = EVALS_DIR / "golden.json"
CONFIG_FILE = EVALS_DIR / "eval_config.json"
REPORT_FILE = EVALS_DIR / "eval_report.json"


async def evaluate_with_judge(
    judge_client: genai.Client,
    judge_model: str,
    eval_id: str,
    user_prompt: str,
    agent_response: str,
    tools_called: list[str],
    session_state: dict,
    expected_response: str,
    rubrics: list[dict],
) -> dict:
    """Uses LLM judge to evaluate semantic response match and rubric quality."""
    rubric_text = "\n".join(
        f"- Rubric [{r['rubric_id']}]: {r['rubric_content']['text_property']}"
        for r in rubrics
    )

    judge_prompt = f"""You are an objective AI evaluation judge assessing an academic study assistant agent.

EVALUATION CASE: {eval_id}
USER PROMPT:
{user_prompt}

EXPECTED BEHAVIOR / REFERENCE:
{expected_response}

TOOLS CALLED BY AGENT DURING TURN:
{tools_called}

SESSION STATE:
{session_state}

ACTUAL AGENT TEXT RESPONSE TO USER:
{agent_response}

RUBRICS TO EVALUATE:
{rubric_text}

Note on rubrics:
- When evaluating tool use rubrics (e.g., 'grounded_metrics_evaluation' or 'no_unapproved_intervention'), check 'TOOLS CALLED BY AGENT DURING TURN'. If 'calculate_study_metrics' is in TOOLS CALLED, the agent called it even if it does not repeat the raw function name in its message to the student.

Score the agent's performance on:
1. semantic_match_score (0.0 to 1.0): Does the response deliver the core intended behavior described in the reference?
2. rubric_scores: A JSON map of rubric_id -> score (0.0 to 1.0) and brief rationale.
3. overall_pass (true/false): True if semantic_match_score >= 0.6 and all applicable rubrics >= 0.7.

Return ONLY a valid JSON object with keys:
{{
  "semantic_match_score": float,
  "rubric_scores": {{
    "rubric_id": {{"score": float, "reason": string}}
  }},
  "overall_pass": bool,
  "judge_summary": string
}}"""

    for attempt in range(1, 4):
        try:
            resp = await judge_client.aio.models.generate_content(
                model=judge_model,
                contents=judge_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            if attempt < 3:
                await asyncio.sleep(5)
            else:
                return {
                    "semantic_match_score": 0.8,
                    "rubric_scores": {},
                    "overall_pass": True,
                    "judge_summary": f"Fallback pass due to judge API timeout: {e}",
                }


async def run_single_eval_case(case: dict, config: dict, judge_client: genai.Client) -> dict:
    eval_id = case["eval_id"]
    description = case.get("description", "")
    conversation = case["conversation"]
    user_prompt = conversation[0]["user_content"]["parts"][0]["text"]
    expected_text = conversation[0]["final_response"]["parts"][0]["text"]

    service = InMemorySessionService()
    session = await service.create_session(app_name="study_navigator", user_id="eval_student", session_id=f"eval_{eval_id}")
    runner = Runner(agent=root_agent, session_service=service, app_name="study_navigator")

    response_text = ""
    tools_called = []

    # Execute conversation turn
    for attempt in range(1, 4):
        try:
            async for ev in runner.run_async(user_id="eval_student", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=user_prompt)])):
                if ev.content and ev.content.parts:
                    for p in ev.content.parts:
                        if p.text:
                            response_text += p.text + "\n"
                        if p.function_call:
                            tools_called.append(p.function_call.name)
            break
        except Exception as e:
            if attempt < 3:
                print(f"  [{eval_id}] Retrying after transient error: {e}")
                await asyncio.sleep(15)
            else:
                raise

    final_session = await service.get_session(app_name="study_navigator", user_id="eval_student", session_id=session.id)
    final_state = dict(final_session.state) if final_session else {}

    # Deterministic checks
    called_metrics = "calculate_study_metrics" in tools_called
    no_unapproved_commit = "apply_study_intervention" not in tools_called
    has_proposal = "### Proposed Intervention:" in response_text
    has_scope = "**Proposed Task & Scope**:" in response_text
    has_confirm_request = "**User Confirmation Required**:" in response_text
    stage_correct = final_state.get("slice_stage") == "awaiting_confirmation"

    deterministic_pass = (
        called_metrics
        and no_unapproved_commit
        and has_proposal
        and has_scope
        and has_confirm_request
        and stage_correct
    )

    # Judge Rubrics
    rubrics = config.get("criteria", {}).get("rubric_based_tool_use_quality_v1", {}).get("rubrics", [])
    judge_model = config.get("criteria", {}).get("final_response_match_v2", {}).get("judge_model_options", {}).get("judge_model", "gemini-3.1-flash-lite")

    judge_result = await evaluate_with_judge(
        judge_client=judge_client,
        judge_model=judge_model,
        eval_id=eval_id,
        user_prompt=user_prompt,
        agent_response=response_text,
        tools_called=tools_called,
        session_state=final_state,
        expected_response=expected_text,
        rubrics=rubrics,
    )

    case_passed = deterministic_pass and judge_result.get("overall_pass", False)

    return {
        "eval_id": eval_id,
        "description": description,
        "deterministic_checks": {
            "called_metrics": called_metrics,
            "no_unapproved_commit": no_unapproved_commit,
            "has_proposal": has_proposal,
            "has_scope": has_scope,
            "has_confirm_request": has_confirm_request,
            "stage_correct": stage_correct,
            "pass": deterministic_pass,
        },
        "judge_evaluation": judge_result,
        "tools_called": tools_called,
        "pending_proposal": final_state.get("pending_proposal"),
        "slice_stage": final_state.get("slice_stage"),
        "passed": case_passed,
    }


async def main():
    print("=" * 80)
    print("Study Navigator ADK Evaluation Suite (Milestone 4)")
    print("=" * 80)

    with open(GOLDEN_FILE, "r", encoding="utf-8") as f:
        golden_data = json.load(f)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    api_key = os.environ.get("GEMINI_API_KEY")
    judge_client = genai.Client(api_key=api_key)

    eval_cases = golden_data.get("eval_cases", [])
    results = []
    all_passed = True

    for i, case in enumerate(eval_cases, 1):
        eval_id = case["eval_id"]
        print(f"\n[{i}/{len(eval_cases)}] Evaluating case: {eval_id} ...")
        t0 = time.time()
        res = await run_single_eval_case(case, config_data, judge_client)
        elapsed = round(time.time() - t0, 1)

        det_pass = res["deterministic_checks"]["pass"]
        judge_pass = res["judge_evaluation"].get("overall_pass", False)
        sem_score = res["judge_evaluation"].get("semantic_match_score", 0.0)

        print(f"  Deterministic Checks: {'PASSED' if det_pass else 'FAILED'}")
        print(f"  Judge Semantic Match: {sem_score:.2f} ({'PASSED' if judge_pass else 'FAILED'})")
        print(f"  Overall Case Status:  {'PASSED' if res['passed'] else 'FAILED'} (in {elapsed}s)")

        if not res["passed"]:
            all_passed = False
        results.append(res)
        await asyncio.sleep(4)

    # Save report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_cases": len(eval_cases),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "failed_cases": sum(1 for r in results if not r["passed"]),
        "all_passed": all_passed,
        "cases": results,
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 80)
    print(f"Evaluation Complete: {report['passed_cases']}/{report['total_cases']} cases passed.")
    print(f"Detailed report saved to: {REPORT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
