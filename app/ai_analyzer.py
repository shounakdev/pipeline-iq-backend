import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def analyze_pipeline_report(
    pipeline_status: str,
    execution_logs: list[str],
    sonar_report: dict
):
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    combined_logs = "\n".join(execution_logs[-120:])

    if not api_key or api_key == "your_openai_api_key_here":
        return fallback_pipeline_analyzer(
            pipeline_status=pipeline_status,
            execution_logs=combined_logs,
            sonar_report=sonar_report
        )

    client = OpenAI(api_key=api_key)

    schema = {
        "type": "object",
        "properties": {
            "final_status": {
                "type": "string",
                "enum": ["PASS", "PASS_WITH_WARNINGS", "FAILED"]
            },
            "overall_summary": {"type": "string"},
            "log_summary": {"type": "string"},
            "sonarqube_summary": {"type": "string"},
            "priority_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "priority": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"]
                        },
                        "issue": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "suggested_fix": {"type": "string"},
                        "helpful_link": {
                            "type": ["string", "null"]
                        }
                    },
                    "required": [
                        "priority",
                        "issue",
                        "why_it_matters",
                        "suggested_fix",
                        "helpful_link"
                    ],
                    "additionalProperties": False
                }
            },
            "how_to_pass": {
                "type": "array",
                "items": {"type": "string"}
            },
            "confidence": {"type": "number"}
        },
        "required": [
            "final_status",
            "overall_summary",
            "log_summary",
            "sonarqube_summary",
            "priority_items",
            "how_to_pass",
            "confidence"
        ],
        "additionalProperties": False
    }

    prompt = f"""
You are a senior DevOps engineer.

Analyze this CI/CD pipeline.

Pipeline status:
{pipeline_status}

Execution logs:
{combined_logs}

SonarQube report:
{json.dumps(sonar_report, indent=2)}

Rules:
- If build/test failed, final_status must be FAILED.
- If build/test passed but npm audit, lint warnings, SonarQube issues, low coverage, bugs, vulnerabilities, or code smells exist, final_status should be PASS_WITH_WARNINGS.
- If everything is clean and quality gate passed, final_status should be PASS.
- Prioritize security vulnerabilities first.
- Give practical fixes.
- Include SonarQube report link when useful.
"""

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "pipeline_ai_report",
                    "schema": schema,
                    "strict": True
                }
            }
        )

        return json.loads(response.output_text)

    except Exception as error:
        fallback = fallback_pipeline_analyzer(
            pipeline_status=pipeline_status,
            execution_logs=combined_logs,
            sonar_report=sonar_report
        )

        fallback["overall_summary"] = (
            fallback["overall_summary"]
            + f" AI fallback used because: {str(error)}"
        )

        return fallback


def fallback_pipeline_analyzer(
    pipeline_status: str,
    execution_logs: str,
    sonar_report: dict
):
    lower_logs = execution_logs.lower()

    coverage = sonar_report.get("coverage") or 0
    bugs = sonar_report.get("bugs") or 0
    vulnerabilities = sonar_report.get("vulnerabilities") or 0
    code_smells = sonar_report.get("code_smells") or 0
    quality_gate = sonar_report.get("quality_gate", "UNKNOWN")
    report_url = sonar_report.get("report_url")

    priority_items = []

    if "critical" in lower_logs or vulnerabilities > 0:
        priority_items.append({
            "priority": "HIGH",
            "issue": "Security vulnerabilities were detected.",
            "why_it_matters": "Critical or high vulnerabilities can expose the application to attacks.",
            "suggested_fix": "Run npm audit, identify affected packages, upgrade dependencies, and rerun the pipeline.",
            "helpful_link": report_url
        })

    if pipeline_status == "FAILED":
        priority_items.append({
            "priority": "HIGH",
            "issue": "Pipeline failed.",
            "why_it_matters": "Failed pipelines block safe deployment.",
            "suggested_fix": "Start with the first failing command in logs, fix it, then rerun the pipeline.",
            "helpful_link": None
        })

    if coverage < 70:
        priority_items.append({
            "priority": "MEDIUM",
            "issue": f"Coverage is below recommended threshold: {coverage}%.",
            "why_it_matters": "Low coverage increases risk of undetected bugs.",
            "suggested_fix": "Add tests for critical business logic and generate LCOV coverage before SonarQube scan.",
            "helpful_link": report_url
        })

    if "warning" in lower_logs or bugs > 0 or code_smells > 0:
        priority_items.append({
            "priority": "LOW",
            "issue": f"Warnings or maintainability issues found. Bugs: {bugs}, Code smells: {code_smells}.",
            "why_it_matters": "Warnings and code smells may reduce maintainability over time.",
            "suggested_fix": "Fix lint warnings, unused variables, React hook dependency warnings, and SonarQube issues.",
            "helpful_link": report_url
        })

    if pipeline_status == "SUCCESS" and quality_gate in ["OK", "PASSED"] and not priority_items:
        final_status = "PASS"
    elif pipeline_status == "SUCCESS":
        final_status = "PASS_WITH_WARNINGS"
    else:
        final_status = "FAILED"

    return {
        "final_status": final_status,
        "overall_summary": f"Pipeline finished with status {pipeline_status}. Quality gate: {quality_gate}.",
        "log_summary": "The logs were analyzed using fallback logic. Check npm, build, test, and scanner warnings.",
        "sonarqube_summary": (
            f"Coverage: {coverage}%, Bugs: {bugs}, "
            f"Vulnerabilities: {vulnerabilities}, Code smells: {code_smells}, "
            f"Quality gate: {quality_gate}."
        ),
        "priority_items": priority_items,
        "how_to_pass": [
            "Fix any failed build or test command first.",
            "Resolve critical/high security vulnerabilities.",
            "Fix SonarQube quality gate failures.",
            "Improve test coverage if it is below threshold.",
            "Rerun the pipeline after fixes."
        ],
        "confidence": 0.7
    }