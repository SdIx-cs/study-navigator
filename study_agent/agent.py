from google.adk import Agent

def get_study_context():
    return {
        "module overviews": {
            "AI": "Artificial Intelligence and Intelligent Systems",
            "DB": "Advanced Database Management"
        },
        "Lecture progress": {
            "AI": "7/10 lectures | 2/3 courseworks",
            "DB": "8/10 lectures | 0/1 courseworks"
        },
        "Current progress": {
            "AI": "5/10 lectures | 1/3 courseworks",
            "DB": "4/10 lectures | 0/1 courseworks"
        }
    }


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
    """,
    tools=[get_study_context]
)