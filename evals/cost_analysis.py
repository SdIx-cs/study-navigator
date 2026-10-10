"""Cost and Model Architecture Analysis for Study Navigator (Milestone 5).

Evaluates token consumption, pricing economics, and latency trade-offs across Gemini model tiers:
- gemini-3.1-flash-lite (production choice)
- gemini-2.5-flash
- gemini-1.5-pro
"""

import json
import pathlib
import time

STUDY_NAV_PATH = pathlib.Path(__file__).resolve().parents[1]
REPORT_PATH = STUDY_NAV_PATH / "evals" / "cost_analysis_report.json"

# Pricing table per million tokens (USD)
MODEL_PRICING = {
    "gemini-3.1-flash-lite": {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
        "avg_latency_seconds": 1.2,
        "recommended_tier": "Default Production",
    },
    "gemini-2.5-flash": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "avg_latency_seconds": 2.1,
        "recommended_tier": "Complex Multi-Turn Evaluation",
    },
    "gemini-1.5-pro": {
        "input_per_million": 1.25,
        "output_per_million": 5.00,
        "avg_latency_seconds": 4.5,
        "recommended_tier": "Offline Complex Reasoning",
    },
}

# Empirical payload sizes derived from Milestone 4 evals
TOKEN_METRICS = {
    "avg_input_tokens_per_checkin": 1450,    # Instruction + Study Context + Tool schemas + User Check-in
    "avg_output_tokens_per_checkin": 320,    # Structured Proposal with scope and steps
    "avg_checkins_per_student_semester": 60, # ~3-4 check-ins per week over 15-week semester
    "cohort_size": 1000,                     # Active student population
}


def run_cost_analysis() -> dict:
    in_tok = TOKEN_METRICS["avg_input_tokens_per_checkin"]
    out_tok = TOKEN_METRICS["avg_output_tokens_per_checkin"]
    checkins_semester = TOKEN_METRICS["avg_checkins_per_student_semester"]
    cohort = TOKEN_METRICS["cohort_size"]

    analysis = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "assumptions": {
            **TOKEN_METRICS,
            "total_tokens_per_interaction": in_tok + out_tok,
            "cohort_interactions_per_semester": cohort * checkins_semester,
        },
        "models": {},
    }

    print("=" * 80)
    print("Study Navigator: Cost & Model Architecture Analysis (Milestone 5)")
    print("=" * 80)
    print(f"Assumed Per-Checkin Footprint: {in_tok} input tokens, {out_tok} output tokens")
    print(f"Cohort Scale: {cohort:,} students x {checkins_semester} check-ins = {cohort * checkins_semester:,} total calls/semester\n")

    for model, cfg in MODEL_PRICING.items():
        cost_input_single = (in_tok / 1_000_000) * cfg["input_per_million"]
        cost_output_single = (out_tok / 1_000_000) * cfg["output_per_million"]
        cost_single = cost_input_single + cost_output_single

        cost_student_semester = cost_single * checkins_semester
        cost_cohort_semester = cost_student_semester * cohort

        model_res = {
            "tier": cfg["recommended_tier"],
            "latency": f"{cfg['avg_latency_seconds']}s",
            "cost_per_checkin_usd": round(cost_single, 6),
            "cost_per_student_semester_usd": round(cost_student_semester, 4),
            "cost_per_cohort_semester_usd": round(cost_cohort_semester, 2),
        }
        analysis["models"][model] = model_res

        print(f"Model: {model} [{cfg['recommended_tier']}]")
        print(f"  Cost / check-in:          ${cost_single:.6f}")
        print(f"  Cost / student / term:    ${cost_student_semester:.4f}")
        print(f"  Cost for 1,000 students:  ${cost_cohort_semester:.2f} / semester")
        print(f"  Est. Turn Latency:        {cfg['avg_latency_seconds']}s\n")

    # Key Architectural Takeaway
    flash_lite_cost = analysis["models"]["gemini-3.1-flash-lite"]["cost_per_cohort_semester_usd"]
    pro_cost = analysis["models"]["gemini-1.5-pro"]["cost_per_cohort_semester_usd"]
    savings_pct = ((pro_cost - flash_lite_cost) / pro_cost) * 100

    analysis["architectural_finding"] = (
        f"Using gemini-3.1-flash-lite delivers sub-1.5s responsive check-ins while achieving "
        f"{savings_pct:.1f}% cost savings over 1.5-pro ($ {flash_lite_cost} vs $ {pro_cost} per 1,000 students/term). "
        f"Deterministic calculation offloaded to calculate_study_metrics ensures zero degradation in "
        f"mathematical precision despite using the lightweight model."
    )

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2)

    print("=" * 80)
    print(f"Report saved to: {REPORT_PATH}")
    print("=" * 80)
    return analysis


if __name__ == "__main__":
    run_cost_analysis()
