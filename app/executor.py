import os
import subprocess
import tempfile
from app.sonar_service import run_sonar_scan


def run_command(command: list[str], cwd: str | None = None, log_fn=None, timeout: int = 180):
    command_text = " ".join(command)

    if log_fn:
        log_fn(f"$ {command_text}")

    try:
        env = os.environ.copy()

        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = ""

        if result.stdout:
            output += result.stdout

        if result.stderr:
            output += result.stderr

        if output.strip() and log_fn:
            log_fn(output.strip())

        return {
            "success": result.returncode == 0,
            "output": output,
            "return_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        output = f"Command timed out: {command_text}"

        if log_fn:
            log_fn(output)

        return {
            "success": False,
            "output": output,
            "return_code": -1,
        }


def execute_node_pipeline(repo_url: str, branch: str):
    logs = []

    def log(message: str):
        if not message:
            return

        clean_message = str(message).strip()

        if not clean_message:
            return

        # Prevent immediate duplicate lines
        if logs and logs[-1] == clean_message:
            return

        logs.append(clean_message)

    log("Starting real Node.js pipeline execution...")
    log(f"Repo: {repo_url}")
    log(f"Branch: {branch}")

    with tempfile.TemporaryDirectory() as temp_dir:
        clone_result = run_command(
            ["git", "clone", repo_url, "repo"],
            cwd=temp_dir,
            log_fn=log,
            timeout=300,
        )

        if not clone_result["success"]:
            return {
                "success": False,
                "logs": logs,
                "failure_reason": "Git clone failed",
            }

        repo_path = os.path.join(temp_dir, "repo")

        checkout_result = run_command(
            ["git", "checkout", branch],
            cwd=repo_path,
            log_fn=log,
            timeout=120,
        )

        if not checkout_result["success"]:
            return {
                "success": False,
                "logs": logs,
                "failure_reason": "Branch checkout failed",
            }

        package_json_path = os.path.join(repo_path, "package.json")

        if not os.path.exists(package_json_path):
            log("package.json not found. Only Node.js projects are supported right now.")

            return {
                "success": False,
                "logs": logs,
                "failure_reason": "package.json not found. Only Node.js projects are supported right now.",
            }

        package_lock_path = os.path.join(repo_path, "package-lock.json")

        if os.path.exists(package_lock_path):
            install_command = ["npm", "ci"]
        else:
            install_command = ["npm", "install"]

        install_result = run_command(
            install_command,
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not install_result["success"]:
            return {
                "success": False,
                "logs": logs,
                "failure_reason": "npm install failed",
            }

        test_result = run_command(
            ["npm", "test"],
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not test_result["success"]:
            return {
                "success": False,
                "logs": logs,
                "failure_reason": "npm test failed",
            }

        build_result = run_command(
            ["npm", "run", "build"],
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not build_result["success"]:
            return {
                "success": False,
                "logs": logs,
                "failure_reason": "npm run build failed",
            }

        project_key = os.getenv("SONARQUBE_PROJECT_KEY", "cicd-demo")

        sonar_result = run_sonar_scan(
            repo_path=repo_path,
            project_key=project_key,
            log_fn=log,
        )

        # MVP/demo behavior:
        # Build/test failures fail the pipeline.
        # SonarQube failures/timeouts are warnings only, so demo is not blocked.
        if sonar_result.get("skipped"):
            log("WARNING: SonarQube scan skipped. Continuing because build and tests passed.")

        elif not sonar_result.get("success"):
            log("WARNING: SonarQube scan failed or timed out. Continuing because build and tests passed.")
            log(
                "SonarQube issue: "
                + str(
                    sonar_result.get("error")
                    or sonar_result.get("failure_reason")
                    or "Unknown SonarQube scan issue"
                )
            )

        else:
            log("SonarQube scan completed successfully.")

        return {
            "success": True,
            "logs": logs,
            "failure_reason": None,
        }
