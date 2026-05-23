import os
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()


def get_sonar_url():
    return (
        os.getenv("SONARQUBE_URL")
        or os.getenv("SONARQUBE_HOST")
        or os.getenv("SONARQUBE_HOST_URL")
        or "http://sonarqube:9000"
    )


def get_sonar_token():
    return os.getenv("SONARQUBE_TOKEN", "")


def get_default_project_key():
    return os.getenv("SONARQUBE_PROJECT_KEY", "cicd-demo")


def normalize_quality_gate_status(status: str):
    if status == "OK":
        return "PASSED"
    if status == "ERROR":
        return "FAILED"
    if status == "WARN":
        return "WARNING"
    return status or "UNKNOWN"


def run_sonar_scan(repo_path: str, project_key: str | None = None, log_fn=None):
    sonar_url = get_sonar_url()
    sonar_token = get_sonar_token()
    project_key = project_key or get_default_project_key()

    if not sonar_url or not sonar_token or not project_key:
        message = (
            "SonarQube scan skipped because SONARQUBE_URL, "
            "SONARQUBE_TOKEN, or SONARQUBE_PROJECT_KEY is missing."
        )

        if log_fn:
            log_fn(message)

        return {
            "success": True,
            "skipped": True,
            "output": message,
            "return_code": -1,
            "project_key": project_key,
        }

    command = [
        "npx",
        "@sonar/scan",
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.projectName={project_key}",
        "-Dsonar.sources=.",
        f"-Dsonar.host.url={sonar_url}",
        f"-Dsonar.login={sonar_token}",
        "-Dsonar.sourceEncoding=UTF-8",
        "-Dsonar.exclusions=node_modules/**,.next/**,dist/**,build/**,coverage/**",
        "-Dsonar.qualitygate.wait=true",
        "-Dsonar.qualitygate.timeout=300",
    ]

    command_text = " ".join(command)

    if log_fn:
        log_fn(f"$ {command_text}")

    try:
        env = os.environ.copy()

        result = subprocess.run(
            command,
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=420,
        )

        output = ""

        if result.stdout:
            output += result.stdout

        if result.stderr:
            output += result.stderr

        output = output.strip()

        if output and log_fn:
            log_fn(output)

        return {
            "success": result.returncode == 0,
            "skipped": False,
            "output": output,
            "return_code": result.returncode,
            "project_key": project_key,
        }

    except subprocess.TimeoutExpired:
        message = "SonarQube scan timed out."

        if log_fn:
            log_fn(message)

        return {
            "success": False,
            "skipped": False,
            "output": message,
            "return_code": -1,
            "project_key": project_key,
        }


def get_sonar_report(project_key: str | None = None):
    sonar_url = get_sonar_url()
    sonar_token = get_sonar_token()
    project_key = project_key or get_default_project_key()

    browser_sonar_url = os.getenv("SONARQUBE_BROWSER_URL", "http://localhost:9000")
    report_url = f"{browser_sonar_url}/dashboard?id={project_key}" if project_key else None

    if not sonar_url or not sonar_token or not project_key:
        return {
            "available": False,
            "message": "SonarQube configuration missing.",
            "coverage": None,
            "bugs": None,
            "vulnerabilities": None,
            "code_smells": None,
            "duplicated_lines_density": None,
            "quality_gate": "UNKNOWN",
            "raw_quality_gate": "UNKNOWN",
            "issues": [],
            "report_url": report_url,
            "project_key": project_key,
        }

    report = {
        "available": True,
        "message": "SonarQube report fetched successfully",
        "coverage": 0,
        "bugs": 0,
        "vulnerabilities": 0,
        "code_smells": 0,
        "duplicated_lines_density": 0,
        "quality_gate": "UNKNOWN",
        "raw_quality_gate": "UNKNOWN",
        "issues": [],
        "report_url": report_url,
        "project_key": project_key,
    }

    auth = (sonar_token, "")

    try:
        measures_response = requests.get(
            f"{sonar_url}/api/measures/component",
            params={
                "component": project_key,
                "metricKeys": (
                    "coverage,bugs,vulnerabilities,"
                    "code_smells,duplicated_lines_density"
                ),
            },
            auth=auth,
            timeout=30,
        )

        measures_response.raise_for_status()

        measures = measures_response.json().get("component", {}).get("measures", [])

        for measure in measures:
            metric = measure.get("metric")
            value = measure.get("value", 0)

            if metric in report:
                report[metric] = float(value)

        gate_response = requests.get(
            f"{sonar_url}/api/qualitygates/project_status",
            params={"projectKey": project_key},
            auth=auth,
            timeout=30,
        )

        gate_response.raise_for_status()

        raw_quality_gate = (
            gate_response.json()
            .get("projectStatus", {})
            .get("status", "UNKNOWN")
        )

        report["raw_quality_gate"] = raw_quality_gate
        report["quality_gate"] = normalize_quality_gate_status(raw_quality_gate)

        issues_response = requests.get(
            f"{sonar_url}/api/issues/search",
            params={
                "componentKeys": project_key,
                "resolved": "false",
                "ps": 10,
            },
            auth=auth,
            timeout=30,
        )

        issues_response.raise_for_status()

        issues = issues_response.json().get("issues", [])

        report["issues"] = [
            {
                "key": issue.get("key"),
                "severity": issue.get("severity"),
                "type": issue.get("type"),
                "message": issue.get("message"),
                "component": issue.get("component"),
                "line": issue.get("line"),
                "rule": issue.get("rule"),
            }
            for issue in issues
        ]

        return report

    except Exception as e:
        return {
            "available": False,
            "message": f"Failed to fetch SonarQube report: {str(e)}",
            "coverage": None,
            "bugs": None,
            "vulnerabilities": None,
            "code_smells": None,
            "duplicated_lines_density": None,
            "quality_gate": "UNKNOWN",
            "raw_quality_gate": "UNKNOWN",
            "issues": [],
            "report_url": report_url,
            "project_key": project_key,
        }