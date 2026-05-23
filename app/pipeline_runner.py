import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path


class PipelineExecutionError(Exception):
    pass


def _emit(logs, text, on_log=None):
    logs.append(text)
    if on_log:
        on_log("".join(logs))


def _run_command(command, cwd, logs, timeout_seconds=900, env=None, on_log=None):
    command_text = " ".join(command)
    _emit(logs, f"\n$ {command_text}\n", on_log)

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, **(env or {})},
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        _emit(logs, output, on_log)
        raise PipelineExecutionError(
            f"Command timed out after {timeout_seconds} seconds: {command_text}"
        )

    output = result.stdout or ""
    _emit(logs, output, on_log)

    if result.returncode != 0:
        raise PipelineExecutionError(
            f"Command failed with exit code {result.returncode}: {command_text}"
        )





def execute_node_pipeline(repo_url: str, branch: str = "main", on_log=None, on_progress=None):
    logs = []

    if not repo_url.startswith("https://github.com/"):
        raise PipelineExecutionError(
            "For MVP safety, only public HTTPS GitHub repo URLs are allowed."
        )

    base_workdir = Path(os.getenv("PIPELINE_WORKDIR", "/tmp/intelligent-cicd-runs"))
    run_folder = base_workdir / uuid.uuid4().hex
    repo_folder = run_folder / "repo"

    base_workdir.mkdir(parents=True, exist_ok=True)

    try:
        if on_progress:
            on_progress(10)

        _emit(logs, "Starting real Node.js pipeline execution...\n", on_log)
        _emit(logs, f"Repo: {repo_url}\n", on_log)
        _emit(logs, f"Branch: {branch}\n", on_log)

        if on_progress:
            on_progress(20)

        _run_command(
            ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(repo_folder)],
            cwd=base_workdir,
            logs=logs,
            timeout_seconds=300,
            on_log=on_log,
        )

        if on_progress:
            on_progress(35)
        # MVP limitation:
        # For now, this pipeline only supports Node.js projects.
        # A repo must contain package.json with scripts.test and scripts.build.
        # Python, Java, Go, Rust, etc. are intentionally not supported yet.
        package_json_path = repo_folder / "package.json"

        if not package_json_path.exists():
            raise PipelineExecutionError(
                "package.json not found. Only Node.js projects."
            )

        _emit(logs, "\npackage.json found. Node.js project detected.\n", on_log)
        
        with open(package_json_path, "r", encoding="utf-8") as file:
            package_data = json.load(file)

        scripts = package_data.get("scripts", {})

        if "test" not in scripts:
            raise PipelineExecutionError(
                "Missing npm test script. Add scripts.test in package.json."
            )

        if "build" not in scripts:
            raise PipelineExecutionError(
                "Missing npm build script. Add scripts.build in package.json."
     )

        _emit(logs, "Required npm scripts found: test and build.\n", on_log)

        if on_progress:
            on_progress(45)

        _run_command(
            ["npm", "install"],
            cwd=repo_folder,
            logs=logs,
            timeout_seconds=900,
            on_log=on_log,
        )

        if on_progress:
            on_progress(65)

      
        _run_command(
            ["npm", "test"],
            cwd=repo_folder,
            logs=logs,
            timeout_seconds=900,
            env={"CI": "true"},
            on_log=on_log,
        )

        if on_progress:
            on_progress(85)


        _run_command(
            ["npm", "run", "build"],
            cwd=repo_folder,
            logs=logs,
            timeout_seconds=900,
            env={"CI": "true"},
            on_log=on_log,
        )

        if on_progress:
            on_progress(100)

        _emit(logs, "\nPipeline completed successfully.\n", on_log)

        return {
            "success": True,
            "logs": "".join(logs),
        }

    except Exception as error:
        _emit(logs, f"\nPipeline failed: {str(error)}\n", on_log)

        return {
            "success": False,
            "logs": "".join(logs),
            "error": str(error),
        }

    finally:
        keep_workdir = os.getenv("KEEP_PIPELINE_WORKDIR", "false").lower() == "true"

        if not keep_workdir and run_folder.exists():
            shutil.rmtree(run_folder, ignore_errors=True)