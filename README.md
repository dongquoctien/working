# Task Orchestrator

> 🤖 Automate Jira/Redmine tasks with Claude CLI - A desktop TUI tool that reads tasks, implements them using AI, runs tests, and creates PRs automatically.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 📋 Table of Contents

- [Features](#-features)
- [Workflow](#-workflow)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Architecture](#-architecture)
- [Supported Platforms](#-supported-platforms)

## ✨ Features

- **Multi-Tracker Support**: Works with both **Jira** and **Redmine**
- **Claude CLI Integration**: AI-powered code implementation and bug fixing
- **Auto Test Loop**: Run tests → fix failures → retry until pass (configurable max retries)
- **Bitbucket Integration**: Automatic branch creation and pull requests
- **Beautiful TUI**: Terminal UI with real-time progress tracking
- **Flexible Configuration**: YAML config with environment variable support
- **Per-Project Tracker**: Different projects can use different trackers

## 🔄 Workflow

```
┌──────────────────┐
│   Fetch Task     │ ← Read from Jira/Redmine
│   from Tracker   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Claude CLI     │ ← AI implements the task
│   Implement      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐         ┌────────────┐         ┌──────────────┐
│    Run Tests     │────────►│   FAIL?    │────────►│  Claude Fix  │
└────────┬─────────┘         └────────────┘         └───────┬──────┘
         │ PASS                                              │
         │                          ┌────────────────────────┘
         ▼                          │ (loop up to N times)
┌──────────────────┐                │
│   Create PR      │◄───────────────┘
│   Update Tracker │
└──────────────────┘
```

## 🚀 Installation

### Prerequisites

- **Python 3.11+**
- **Claude CLI** installed and configured ([Installation Guide](https://docs.anthropic.com/claude-code))
- **Git**
- **Jira** account with API token OR **Redmine** account with API key
- **Bitbucket** account with app password

### Setup

1. **Clone the repository**
```bash
git clone <repo-url>
cd task-orchestrator
```

2. **Install dependencies**
```bash
pip install -r requirements.txt

# Or install as package
pip install -e .
```

3. **Create configuration files**
```bash
cp config/config.yaml.example config/config.yaml
cp .env.example .env
```

4. **Edit configuration**
```bash
# Edit .env with your API keys
notepad .env

# Edit config/config.yaml with your settings
notepad config/config.yaml
```

5. **Test connections**
```bash
python -m src.main --check
```

## ⚙️ Configuration

### config/config.yaml

```yaml
# =============================================================================
# TRACKER SELECTION
# =============================================================================
tracker: "jira"  # Options: "jira" or "redmine"

# =============================================================================
# JIRA CONFIGURATION
# =============================================================================
jira:
  url: "https://your-company.atlassian.net"
  email: "your-email@company.com"
  api_token: "${JIRA_API_TOKEN}"

# =============================================================================
# REDMINE CONFIGURATION
# =============================================================================
redmine:
  url: "https://redmine.your-company.com"
  api_key: "${REDMINE_API_KEY}"
  done_status: "Closed"
  in_progress_status: "In Progress"

# =============================================================================
# BITBUCKET CONFIGURATION
# =============================================================================
bitbucket:
  workspace: "your-workspace"
  username: "your-username"
  app_password: "${BITBUCKET_APP_PASSWORD}"

# =============================================================================
# PROJECT CONFIGURATIONS
# =============================================================================
projects:
  # Java project (Gradle)
  - name: "backend-api"
    path: "D:/Code/backend-api"
    test_command: "gradlew.bat test"
    build_command: "gradlew.bat build"
    branch_prefix: "feature"
    # Optional: override tracker for this project
    # tracker: "redmine"

  # Angular project
  - name: "frontend-app"
    path: "D:/Code/frontend-app"
    test_command: "npm test"
    build_command: "npm run build"

  # Maven project
  - name: "legacy-service"
    path: "D:/Code/legacy-service"
    test_command: "mvn test"
    tracker: "redmine"  # This project uses Redmine

# =============================================================================
# WORKFLOW SETTINGS
# =============================================================================
workflow:
  max_retries: 5              # Max test retry attempts
  retry_delay_seconds: 10     # Delay between retries
  auto_create_pr: true        # Auto create PR after tests pass
  auto_update_tracker: true   # Auto update Jira/Redmine status
  done_status: "Done"
  in_progress_status: "In Progress"

# =============================================================================
# CLAUDE CLI SETTINGS
# =============================================================================
claude:
  model: "sonnet"             # Options: sonnet, opus, haiku
  timeout_minutes: 30
  cli_path: "claude"
```

### Environment Variables (.env)

```bash
# Jira API Token
# Get from: https://id.atlassian.com/manage-profile/security/api-tokens
JIRA_API_TOKEN=your_jira_api_token

# Redmine API Key
# Get from: Redmine → My Account → API access key
REDMINE_API_KEY=your_redmine_api_key

# Bitbucket App Password
# Get from: https://bitbucket.org/account/settings/app-passwords/
# Required permissions: Repositories (read, write), Pull requests (read, write)
BITBUCKET_APP_PASSWORD=your_bitbucket_app_password
```

## 📖 Usage

### TUI Mode (Default)

```bash
python -m src.main
```

**Keyboard Shortcuts:**

| Key | Action |
|-----|--------|
| `a` | Add task (enter issue key) |
| `p` | Pause/Resume orchestrator |
| `c` | Cancel selected task |
| `r` | Refresh task list |
| `q` | Quit application |

**TUI Screenshot:**
```
╔══════════════════════════════════════════════════════════════╗
║                    Task Orchestrator                         ║
╠══════════════════════════════════════════════════════════════╣
║ ┌─────────────────────┐ ┌──────────────────────────────────┐ ║
║ │ Task Queue          │ │ Current Task: DEV-123            │ ║
║ │ ─────────────────── │ │ ──────────────────────────────── │ ║
║ │ ▶ DEV-123 [TESTING] │ │ Status: TESTING (Attempt 2/5)    │ ║
║ │   DEV-124 [PENDING] │ │ Project: backend-api             │ ║
║ │   DEV-125 [DONE ✓]  │ │ Branch: feature/dev-123-add-user │ ║
║ └─────────────────────┘ └──────────────────────────────────┘ ║
╠══════════════════════════════════════════════════════════════╣
║ Live Output:                                                 ║
║ > Running: gradlew test                                      ║
║ > Tests: 45/50 passed                                        ║
║ > FAILED: UserServiceTest.testCreateUser()                   ║
║ > Calling Claude to fix...                                   ║
╠══════════════════════════════════════════════════════════════╣
║ [A]dd Task  [P]ause  [R]efresh  [Q]uit                      ║
╚══════════════════════════════════════════════════════════════╝
```

### Single Task Mode

Run a single task without TUI:

```bash
# Jira task
python -m src.main --run DEV-123

# Redmine task (numeric ID)
python -m src.main --run 12345
```

### Check Connections

```bash
python -m src.main --check
```

Output:
```
╔══════════════════════════════════════════════════════════════╗
║                    Task Orchestrator                         ║
╚══════════════════════════════════════════════════════════════╝

Checking connections...

Active tracker: jira

Claude CLI: OK
Jira: OK
Bitbucket: OK
```

### Debug Mode

```bash
python -m src.main --debug
```

### Custom Config File

```bash
python -m src.main -c /path/to/custom-config.yaml
```

## 🏗️ Architecture

```
task-orchestrator/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py            # Configuration loader
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── state_machine.py       # Task lifecycle states
│   │   ├── task_runner.py         # Single task execution
│   │   └── orchestrator.py        # Queue management
│   │
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract IssueTrackerClient
│   │   ├── jira_client.py         # Jira API client
│   │   ├── redmine_client.py      # Redmine API client
│   │   ├── bitbucket_client.py    # Bitbucket API client
│   │   ├── claude_cli.py          # Claude CLI wrapper
│   │   └── test_runner.py         # Test execution
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── app.py                 # Textual TUI application
│   │   ├── screens/
│   │   └── widgets/
│   │
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Rich logging
│
├── config/
│   └── config.yaml                # User configuration
│
├── logs/                          # Execution logs
├── requirements.txt
├── pyproject.toml
└── README.md
```

### State Machine

```
PENDING → FETCHING → IMPLEMENTING → TESTING →
  ├─► PASSED → CREATING_PR → UPDATING_JIRA → COMPLETED
  └─► FAILED → FIXING → TESTING (loop up to max_retries)
              └─► MAX_RETRIES_EXCEEDED → MANUAL_REVIEW
```

## 🖥️ Supported Platforms

### Issue Trackers

| Tracker | Status | Issue Key Format |
|---------|--------|------------------|
| Jira Cloud | ✅ Supported | `PROJECT-123` |
| Jira Server | ✅ Supported | `PROJECT-123` |
| Redmine | ✅ Supported | `12345` (numeric) |

### Git Platforms

| Platform | Status |
|----------|--------|
| Bitbucket Cloud | ✅ Supported |
| Bitbucket Server | 🔄 Planned |
| GitHub | 🔄 Planned |
| GitLab | 🔄 Planned |

### Build Tools

| Tool | Detection | Test Command |
|------|-----------|--------------|
| Gradle | `build.gradle` / `build.gradle.kts` | `gradlew test` |
| Maven | `pom.xml` | `mvn test` |
| NPM | `package.json` | `npm test` |

## 📝 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

If you encounter any issues, please file an issue on the repository.

---

Made with ❤️ and Claude CLI
