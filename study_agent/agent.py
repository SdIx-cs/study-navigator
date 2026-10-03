from google.adk import Agent

try:
    from .tools import calculate_study_metrics, get_study_context
except ImportError:
    from tools import calculate_study_metrics, get_study_context

root_agent = Agent(
    name="study_navigator",
    model="gemini-3.6-flash",
    description="Helps the user decide what to study next.",
    instruction="""
    You are a study navigator.

    Help the user decide what to study next based on their
    learning goal and current situation.

    Use calculate_study_metrics to inspect deterministic deadlines, lecture deficits,
    and marks at risk.
    Explain things clearly when explanation is useful.
    When practice is more useful, give the user a practice task.
    """,
    tools=[calculate_study_metrics, get_study_context]
)