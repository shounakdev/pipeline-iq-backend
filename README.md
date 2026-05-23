
# Pipeline IQ (Intelligent CICD Backend)

Pipeline IQ is an intelligent CI/CD control-plane dashboard that can trigger real pipeline runs, execute Node.js-based projects, run SonarQube quality scans, store build logs, and generate AI-powered DevOps summaries.

The goal of this project is not to replace Jenkins or GitHub Actions. Instead, Pipeline IQ acts as an intelligence layer on top of CI/CD workflows by giving developers better visibility into pipeline health, code quality, failures, warnings, and improvement suggestions.

This is the backend


## Features

- Trigger pipelines using a repository URL and branch name
- Execute real Node.js/JavaScript/TypeScript projects
- Run `npm ci`, `npm test`, and `npm run build`
- Capture and store real pipeline logs
- Track pipeline status:
  - `PENDING`
  - `RUNNING`
  - `SUCCESS`
  - `FAILED`
- Run SonarQube scans after build completion
- Fetch detailed SonarQube metrics:
  - Coverage
  - Bugs
  - Vulnerabilities
  - Code smells
  - Duplicated lines density
  - Quality gate status
- Extract SonarQube issues and display them in the dashboard
- Generate AI DevOps summaries based on:
  - Pipeline logs
  - Build warnings
  - npm vulnerabilities
  - SonarQube metrics
  - SonarQube issues
- Show priority-wise suggestions:
  - High priority
  - Medium priority
  - Low priority
- View terminal-style logs in the frontend
- Open the full SonarQube report from the dashboard

## Tech Stack

- **Frontend**
  - Next.js
  - TypeScript
  - React
  - Inline CSS Styling

- **Backend**
  - FastAPI
  - Python
  - SQLAlchemy
  - PostgreSQL

- **Queue & Worker**
  - Redis
  - Celery

- **DevOps & Quality**
  - Docker
  - Docker Compose
  - SonarQube
  - Sonar Scanner

- **AI**
  - OpenAI API
  - Fallback Rule-Based Analyzer
## Architecture

```text
Frontend Dashboard
        ↓
FastAPI Backend
        ↓
PostgreSQL Database
        ↓
Redis Queue
        ↓
Celery Worker
        ↓
GitHub Repo Clone
        ↓
npm ci / npm test / npm run build
        ↓
SonarQube Scan
        ↓
AI DevOps Analyzer
        ↓
Dashboard Report
```
## AI DevOps Summary

## AI Analysis Engine

Pipeline IQ analyzes pipeline execution results and classifies them into the following categories:

- `PASS`
- `PASS_WITH_WARNINGS`
- `FAILED`

The AI-generated analysis includes:

- Overall Pipeline Summary
- Execution Log Summary
- SonarQube Quality Summary
- Priority-wise Issues
- Suggested Fixes
- Recommended Steps to Improve or Pass the Pipeline

### Example Response

```json
{
  "final_status": "PASS_WITH_WARNINGS",
  "overall_summary": "Pipeline completed successfully, but warnings and quality issues were detected.",
  "priority_items": [
    {
      "priority": "HIGH",
      "issue": "Security vulnerabilities were detected.",
      "suggested_fix": "Run npm audit and upgrade affected dependencies."
    }
  ]
}
```
## Currently Supported Project Types

## Supported Projects

Pipeline IQ currently supports npm-based JavaScript and TypeScript projects.

### ✅ Supported Now

- Node.js
- React
- Next.js
- Vite
- Express.js
- Basic JavaScript Apps
- Basic TypeScript Apps

### 🚀 Support Coming Soon

- Java Maven / Spring Boot
- Python / FastAPI / Django
- Go
- Rust
- .NET
- Monorepos with Multiple Apps
- Docker-based custom build commands
## Dashboard Capabilities


The dashboard shows:

- Total Pipelines
- Success Rate
- Failure Rate
- Average Pipeline Time
- Pipeline Status
- Quality Gate Status
- Coverage
- Bugs
- Vulnerabilities
- Code Smells
- SonarQube Issues
- AI DevOps Summary
- Priority-wise Suggestions
- Full Execution Logs
## Sample Pipeline Flow

```text
User enters repo URL and branch
        ↓
Backend creates pipeline record
        ↓
Worker picks job from Redis queue
        ↓
Worker clones GitHub repository
        ↓
Worker runs npm ci
        ↓
Worker runs tests
        ↓
Worker runs production build
        ↓
Worker runs SonarQube scan
        ↓
Backend stores metrics and logs
        ↓
AI analyzer generates summary
        ↓
Frontend displays final report
```
## Run Locally

# Setup Instructions

## 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd intelligent-cicd-platform
```

---

## 2. Create Environment File

Create a `.env` file in the root directory.

```env
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/cicd_db
REDIS_URL=redis://redis:6379/0

OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini

SONARQUBE_URL=http://sonarqube:9000
SONARQUBE_BROWSER_URL=http://localhost:9000
SONARQUBE_PROJECT_KEY=cicd-demo
SONARQUBE_TOKEN=your_sonarqube_token_here
```

---

## 3. Start Backend Infrastructure

```bash
docker compose up --build
```

This starts:

- FastAPI Backend
- Celery Worker
- PostgreSQL
- Redis
- SonarQube
- SonarQube Database

---

## 4. Start Frontend

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

### Frontend Runs At

```text
http://localhost:3000
```

### Backend Runs At

```text
http://localhost:8000
```

### SonarQube Runs At

```text
http://localhost:9000
```
## Important Security Note



> ⚠️ Do not commit real API keys or SonarQube tokens to GitHub.

Use `.env` files locally and add them to `.gitignore`.

```gitignore
.env
frontend/.env.local
```
## API Reference

# API Documentation

## Health Check

### Endpoint

```http
GET /health
```

### Response

```json
{
  "status": "ok"
}
```

---

## Trigger Pipeline

### Endpoint

```http
POST /pipeline/trigger
```

### Request

```json
{
  "repo_url": "https://github.com/shounakdev/meetup",
  "branch": "main"
}
```

### Response

```json
{
  "pipeline_id": "pipeline-id",
  "status": "PENDING",
  "message": "Pipeline triggered successfully"
}
```

---

## Get All Pipelines

### Endpoint

```http
GET /pipelines
```

### Response

```json
[
  {
    "id": "pipeline-id",
    "repo_url": "https://github.com/shounakdev/meetup",
    "branch": "main",
    "status": "SUCCESS",
    "quality_gate": "PASSED",
    "coverage": 0,
    "bugs": 1,
    "vulnerabilities": 0,
    "code_smells": 0
  }
]
```

---

## Get Pipeline Details

### Endpoint

```http
GET /pipeline/{pipeline_id}
```

### Response

```json
{
  "id": "pipeline-id",
  "status": "SUCCESS",
  "coverage": 0,
  "bugs": 1,
  "vulnerabilities": 0,
  "code_smells": 0,
  "quality_gate": "PASSED",
  "sonar_report_url": "http://localhost:9000/dashboard?id=cicd-demo",
  "sonar_issues": [],
  "logs": [],
  "analysis": {
    "final_status": "PASS_WITH_WARNINGS",
    "report_json": {
      "overall_summary": "Pipeline finished with warnings.",
      "priority_items": []
    }
  }
}
```
## Roadmap


- Add Java Maven / Spring Boot Support
- Add Python / FastAPI / Django Support
- Add Go Project Support
- Add Rust Project Support
- Add Dockerfile-Based Custom Pipeline Execution
- Add Monorepo Detection
- Add Veracode Security Scanning
- Add GitHub Webhook Support
- Add Authentication and User Accounts
- Add Organization / Team Support
- Add Historical Pipeline Charts
- Add Deployment Support
- Add Email / Slack Notifications
## 🚀 About Me

Made by [Shounak](https://linktr.ee/_shounakchandra) © 2026
## Why This Project Matters


Modern CI/CD pipelines often fail without providing clear explanations. Developers are forced to manually inspect lengthy logs, review quality reports, and identify root causes on their own.

Pipeline IQ solves this problem by combining:

- Real Pipeline Execution
- Code Quality Scanning
- Persistent Logs
- AI-Powered Failure and Warning Analysis
- A Clean Dashboard for Visibility

This makes it easier for teams to understand pipeline health, prioritize fixes, and improve software delivery reliability.

---

## Recommended README Structure

```text
Title and Description
Features
Tech
Run Locally
Environment Variables
API Reference
Screenshots
Roadmap
Authors
```
## License

[MIT](https://choosealicense.com/licenses/mit/)

