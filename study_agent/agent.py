from google.adk import Agent

root_agent = Agent(
    name="study_navigator",
    model="gemini-3.8-flash",
    description="Helps the user decide what to study next.",
    instruction="""
    You are a study navigator.

    Help the user decide what to study next based on their
    learning goal and current situation.

    Explain things clearly when explanation is useful.
    When practice is more useful, give the user a practice task.
    """
)