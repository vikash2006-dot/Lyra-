# LYRA — Modular Personal AI Operating System

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Zero-Cost Budget](https://img.shields.io/badge/budget-₹0%20Zero--Cost-brightgreen.svg)]()
[![Privacy First](https://img.shields.io/badge/privacy-local--first-purple.svg)]()
[![Standard Library First](https://img.shields.io/badge/dependencies-standard--library--first-orange.svg)]()

**LYRA** is an open, modular, zero-cost personal AI operating system designed to run locally on your machine with extreme privacy, multi-provider intelligence, persistent selective memory, safe tool calling, multimodal streaming interaction, background automation, and controlled device interaction.

LYRA requires **no paid cloud subscriptions** (₹0 budget constraint) and maintains a **standard-library-first** architecture with zero runtime bloat.

---

## Key Capabilities

* **Multi-Provider Intelligent Routing**: Seamless automatic failover across free-tier providers (**Gemini 2.5 Flash**, **Groq LLaMA 3.3 70B**, **OpenRouter**, **Cerebras LLaMA 3.3 70B**) and a fully local **Ollama** runtime.
* **Offline & Air-Gapped Mode (`--offline`)**: Complete operational independence without cloud dependencies. Switches model routing to local models and disables external tool network requests.
* **Streaming & Multimodal Interaction**: Progressive token streaming with live CLI delta emission, image inspection, and file analysis via unified typed payloads.
* **Selective, Epistemic Memory**: SQLite-backed user memory store that isolates facts, preferences, goals, habits, and tasks with confidence scoring and automatic TTL expiration.
* **Safe Tool Architecture**: Standard library tools for deterministic system time, Open-Meteo weather, DuckDuckGo web search, RSS news, geocoding maps, sandboxed local file management, and computer vision.
* **Autonomous Scheduling & Automation**: SQLite-backed background engine for one-time reminders, recurring intervals, and scheduled tool triggers with exponential backoff and persistent state.
* **Sandboxed Browser Automation**: Playwright-compatible browser engine with strict domain whitelisting, SSRF/private network protection, blocked downloads, and sanitization.
* **Controlled Computer Interaction**: Permission-gated screen capture, mouse movement, keyboard typing, and window switching with a hardware-level Fail-Closed Emergency Stop.
* **Privacy & User Identity**: Local Argon2/PBKDF2-hardened credentials, user isolation, GDPR-compliant full data export (`/export`), and complete account deletion (`/delete-account`).
* **Production Hardened & Zero Credential Leakage**: Custom diagnostic logging with automated scrubbing of API keys, bearer tokens, passwords, cookies, and private key blocks across all logs, exceptions, and user prompts.

---

## Architectural Overview

```text
                                 ┌────────────────────────────────────────────────────────┐
                                 │                   USER INTERFACES                      │
                                 │       Terminal CLI  /  Voice Pipeline (STT/TTS)        │
                                 └──────────────────────────┬─────────────────────────────┘
                                                            │
                                                            ▼
                                 ┌────────────────────────────────────────────────────────┐
                                 │                 COMPANION ORCHESTRATOR                 │
                                 │  * Session State Management    * Identity Isolation    │
                                 │  * Prompt Sanitization         * Streaming Turn Loop   │
                                 └──────────┬───────────────────┬─────────────────────────┘
                                            │                   │
                     ┌──────────────────────┴──────┐     ┌──────┴──────────────────────┐
                     ▼                             │     ▼                             │
    ┌─────────────────────────────────┐            │   ┌───────────────────────────┐   │
    │          MODEL ROUTER           │            │   │       TOOL EXECUTOR       │   │
    │  Priority & Dynamic Fallback    │            │   │  * Loop Limit Protection  │   │
    └────────────────┬────────────────┘            │   │  * Schema Validation      │   │
                     │                             │   └─────────────┬─────────────┘   │
      ┌──────────────┼──────────────┐              │                 │                 │
      ▼              ▼              ▼              │    ┌────────────┼────────────┐    │
┌───────────┐  ┌───────────┐  ┌───────────┐        │    ▼            ▼            ▼    │
│  Gemini   │  │   Groq    │  │ Cerebras  │        │ ┌─────┐   ┌───────────┐ ┌──────┐  │
├───────────┤  ├───────────┤  ├───────────┤        │ │Time │   │  Weather  │ │Search│  │
│OpenRouter │  │   Mock    │  │   LOCAL   │        │ ├─────┤   ├───────────┤ ├──────┤  │
│           │  │           │  │ (Ollama)  │        │ │News │   │   Maps    │ │Files │  │
└───────────┘  └───────────┘  └───────────┘        │ ├─────┤   ├───────────┤ ├──────┤  │
                                                   │ │Memo-│   │  Browser  │ │Compu-│  │
                                                   │ │  ry │   │(Sandboxed)│ │ ter  │  │
                                                   │ └─────┘   └───────────┘ └──────┘  │
                                                   ▼                                   ▼
                                      ┌────────────────────────┐         ┌─────────────────────────┐
                                      │   PERSISTENT MEMORY    │         │  AUTOMATION & SCHEDULER │
                                      │ SQLite Repository      │         │ SQLite Task Queue       │
                                      │ Selective Policies     │         │ Cron & Interval Engine  │
                                      └────────────────────────┘         └─────────────────────────┘
```

---

## Project Structure

```text
Lyra/
├── lyra/
│   ├── auth/              # User identity, local auth provider, session binding
│   ├── automation/        # Background scheduler, triggers, actions, SQLite store
│   ├── browser/           # Controlled browser automation, session management, security policy
│   ├── companion/         # Core conversation orchestrator, prompt builders, session tracking
│   ├── computer/          # Controlled screen, keyboard, mouse controllers with emergency stop
│   ├── config/            # Strict typed settings with .env precedence and validation
│   ├── core/              # Foundational types, base classes, and domain exceptions
│   ├── interfaces/        # Interactive CLI with streaming, slash commands, and multi-user support
│   ├── memory/            # SQLite memory repository, retention policies, epistemic categories
│   ├── models/            # Immutable domain dataclasses (auth, automation, memory, multimodal, stream)
│   ├── observability/     # Secret-scrubbing logging subsystem and diagnostic tracers
│   ├── providers/         # Multi-provider integrations (Gemini, Groq, OpenRouter, Cerebras, Ollama)
│   ├── routing/           # Intelligent priority router with rate-limit cooldown and fallback
│   ├── tools/             # Real-world tools (Search, Weather, News, Time, Maps, Files, Vision)
│   └── voice/             # Speech-to-text, text-to-speech, and audio streaming pipeline
├── tests/
│   ├── unit/              # 350+ unit and hardening test suites with 100% pass rate
│   └── fixtures/          # Test data, mocks, and sample payloads
├── .env.example           # Comprehensive template for configuration and credentials
├── pyproject.toml         # Standard-library-first project specification
└── README.md              # Project documentation
```

---

## Quickstart & Installation

### Requirements
- **Python**: 3.14 or later
- **Operating System**: macOS (Apple Silicon / Intel), Linux, or Windows (WSL2)
- **Zero Cost**: No external paid services required

### 1. Set Up Environment
```bash
git clone https://github.com/your-username/lyra.git
cd Lyra

# Create virtual environment with Python 3.14
python3.14 -m venv .venv
source .venv/bin/activate

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### 2. Configure Settings
```bash
cp .env.example .env
```
Edit `.env` to configure your preferences. All API keys are completely optional.

---

## Configuration Reference (`.env`)

LYRA is fully functional out of the box with default zero-cost configurations:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `LYRA_ENV` | `development` | Environment mode (`development`, `production`, `test`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `OFFLINE_MODE` | `false` | When `true`, cuts off external network calls and forces local Ollama |
| `PROVIDER_PRIORITY` | `gemini,groq,openrouter,cerebras,local` | Priority ordering for model routing |
| `GEMINI_API_KEY` | *(empty)* | Free Google AI Studio API key |
| `GROQ_API_KEY` | *(empty)* | Free Groq Cloud API key |
| `OPENROUTER_API_KEY` | *(empty)* | Free OpenRouter API key |
| `CEREBRAS_API_KEY` | *(empty)* | Free Cerebras Cloud API key |
| `LOCAL_PROVIDER_BASE_URL` | `http://localhost:11434` | Ollama or local LLM server endpoint |
| `LOCAL_PROVIDER_MODEL` | `llama3.2` | Local model name installed in Ollama |
| `MEMORY_DB_PATH` | `~/.lyra/memory.db` | Path to persistent SQLite memory database |
| `AUTOMATION_DB_PATH`| `~/.lyra/automations.db` | Path to background task scheduler store |
| `AUTH_DB_PATH` | `~/.lyra/auth.db` | Path to local authentication & credentials database |
| `COMPUTER_CONTROL_ENABLED` | `false` | Explicit master opt-in for computer interaction |
| `BROWSER_ALLOW_HEADLESS` | `true` | Run browser automation in headless mode |

---

## Usage Guide

### 1. Interactive Terminal Companion
Start the interactive conversational companion:
```bash
lyra
```

### 2. Single-Prompt Execution with Streaming
Run an ad-hoc request with instant streaming response:
```bash
lyra "What is the capital of France and what is the current weather there?"
```

### 3. Multimodal Image & File Inspection
Pass images or local text files directly into LYRA:
```bash
lyra -i /path/to/diagram.png "Explain the architecture shown in this diagram"
lyra -f /path/to/config.json "Validate this configuration file"
```

### 4. Fully Offline / Air-Gapped Mode
Force LYRA to operate without connecting to cloud APIs:
```bash
lyra --offline "Summarize the files in my current directory"
```

### 5. Multi-User Authentication & Slash Commands
Inside the interactive CLI, access identity and automation commands:
- `/register` — Create a local secure account with password hashing
- `/login` — Authenticate and switch user memory contexts
- `/whoami` — Display current authenticated user profile
- `/logout` — Return to anonymous sandboxed session
- `/export` — Export all user profile data and memories as JSON (GDPR compliance)
- `/delete-account` — Permanently purge user profile, memories, and automations
- `/schedule list` — View all pending and recurring background tasks
- `/schedule create <seconds> <message>` — Schedule a reminder notification

---

## Tool Ecosystem

LYRA includes built-in deterministic, standard-library-first tools:

1. **Time (`time_tool`)**: Deterministic local and UTC time, dates, timezones, and day-of-week calculations.
2. **Weather (`weather`)**: Real-time forecasts, temperature, wind speed, and precipitation via the free Open-Meteo API.
3. **Search (`search`)**: Web search with automatic HTML parsing and instant answer fallback via DuckDuckGo and Tavily.
4. **News (`news`)**: Current news headlines fetched directly from public RSS feeds without API keys.
5. **Maps (`maps`)**: Geocoding, coordinates, and reverse address lookup via OpenStreetMap Nominatim.
6. **Files (`file_tool`)**: Sandboxed workspace file operations: read, write, list directories, and view file stats.
7. **Vision (`vision_tool`)**: Visual inspection and multimodal analysis for image files.
8. **Browser (`browser_tool`)**: Controlled web browsing with SSRF protection and domain whitelist enforcement.
9. **Computer (`computer_tool`)**: Permission-gated screen capture and interface interaction with an Emergency Stop switch.
10. **Memory (`memory_tool`)**: Explicit user memory recall, query, search, and storage.

---

## Security, Safety & Hardening

* **Automatic Secret Scrubbing**: All logging formatters and diagnostic handlers pass through a multi-pattern regex filter that masks API keys, bearer tokens, passwords, cookies, and RSA private keys before writing to disk or stdout.
* **Fail-Closed Computer Control**: Computer control requires an explicit boolean flag (`COMPUTER_CONTROL_ENABLED=true`). When triggered, the hardware Emergency Stop immediately halts all active mouse/keyboard actions and rejects further input.
* **SSRF & Private Network Defense**: The browser automation subsystem actively inspects hostnames and IP addresses, immediately blocking access to private network ranges (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.169.254` cloud metadata endpoints).
* **Prompt Injection Neutralization**: Untrusted external web and file content is safely quarantined within structural XML boundary tags (`<untrusted_external_content>`), preventing prompt injection attacks from overriding system instructions.
* **Tool Loop Prevention**: The orchestrator enforces hard recursion limits (maximum 5 chained tool turns) to prevent infinite execution cycles and catastrophic token consumption.

---

## Adaptive Learning Agent
 
 LYRA includes a production-grade, deterministic **Adaptive Learning Agent** designed to continuously guide learners from their current capabilities toward ambitious career goals. Unlike static course recommenders, LYRA continuously diagnoses skill levels, sequences prerequisite Directed Acyclic Graphs (DAGs), strictly respects weekly hour budgets, generates hands-on practice, detects struggles, and dynamically recalculates the active learning plan.
 
 ### Architecture & Flow
 
 ```text
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │                               LEARNER INPUT                                   │
 │   Conversational Intake (CLI/Voice)  *  Resume/Doc Upload  *  Practice Evals  │
 └───────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │                              LEARNING ENGINE                                   │
 │  ┌─────────────────────────┐                     ┌──────────────────────────┐  │
 │  │      Skill Engine       │                     │    Diagnostic Engine     │  │
 │  │ Prerequisite DAG & Sort │                     │ Conversational Questions │  │
 │  └────────────┬────────────┘                     └─────────────┬────────────┘  │
 │               │                                                │               │
 │               ▼                                                ▼               │
 │  ┌─────────────────────────┐                     ┌──────────────────────────┐  │
 │  │      Gap Analyzer       │◄────────────────────│  Evidence & Mastery      │  │
 │  │ Prereq Depth & Severity │                     │  Multi-Source Weighting  │  │
 │  └────────────┬────────────┘                     └─────────────┬────────────┘  │
 │               │                                                │               │
 │               ▼                                                │               │
 │  ┌─────────────────────────┐                     ┌─────────────▼────────────┐  │
 │  │    Objective Engine     │                     │    Struggle Detector     │  │
 │  │ Concrete Milestones &   │                     │ 3 Consecutive Failures   │  │
 │  │ Curated Real Resources  │                     │ Misconception Tracking   │  │
 │  └────────────┬────────────┘                     └─────────────┬────────────┘  │
 │               │                                                │               │
 │               ▼                                                │               │
 │  ┌─────────────────────────┐                                   │               │
 │  │     Plan Generator      │◄──────────────────────────────────┘               │
 │  │ Weekly Hours Bounded    │   (Inserts Remedial Units & Adjusts Pacing)       │
 │  │ Daily Task Breakdown    │                                                   │
 │  └────────────┬────────────┘                                                   │
 └───────────────┼────────────────────────────────────────────────────────────────┘
                 │
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │                      PERSISTENCE & INTEGRATION WIRING                          │
 │  * SQLite Repository (15 normalized tables with thread-safe connection pool)   │
 │  * Bi-directional MemoryManager Sync (Preferences & Goals stored in Memory)    │
 │  * Companion Orchestrator & Tool Registry (17 deterministic Learning Tools)    │
 └────────────────────────────────────────────────────────────────────────────────┘
 ```
 
 ### The Adaptive Planning Loop
 
 1. **Intake & Profiling**: LYRA gathers background details (education, years of experience, current role, target role, weekly available hours, target timeline). If key details are missing, LYRA asks targeted, single-topic diagnostic questions.
 2. **Evidence Collection**: Skills and experience levels (1=Novice, 2=Elementary, 3=Intermediate, 4=Advanced, 5=Expert) are extracted with epistemic confidence weights from self-reports (0.6), resume parsing (0.75), code submissions (0.9), and project completions (1.0). Levels never artificially inflate without verifiable evidence.
 3. **Gap Analysis & DAG Ordering**: The target role's skill requirements are matched against learner skills. Gaps are sequenced using topological sort so foundational prerequisites (e.g., HTTP -> REST APIs -> Authentication) are mastered before advanced topics.
 4. **Strictly Bounded Planning**: Daily and weekly plans strictly enforce the user's available weekly hours budget (e.g., exactly 8 hours/week, not 15).
 5. **Practice & Project Generation**: Hands-on starter code, prompts, rubrics, hints, and capstone project specifications are generated.
 6. **Evaluation & Mastery Calculation**: Submissions are evaluated against real criteria. Mastery scores (0.0–1.0) update dynamically based on weighted evidence.
 7. **Struggle Detection & Adaptation**: When 3 consecutive failures occur on a topic (or explicit misconceptions are identified), LYRA automatically logs a struggle record, flags the weak area in the profile, injects targeted remedial practice, and shifts future milestone schedules. When topics are mastered ahead of schedule, the plan accelerates.
 
 ### CLI and Voice Interaction
 
 In both CLI interactive mode and Voice mode, the learner speaks naturally:
 
 - *"I want to become a Junior Backend Engineer, and I have about 8 hours a week to study."*
 - *"Here is my background: I know beginner Python and basic Git."*
 - *"What should I learn today?"*
 - *"What are my biggest skill gaps right now?"*
 - *"Give me a practice exercise for SQL joins."*
 - *"I'm stuck on SQL joins, can you help me understand what I did wrong?"*
 - *"Show me my active learning plan and weekly progress."*
 
 ### 17 Built-In Learning Tools
 
 - `learning_get_profile`: Inspect current profile, experience, hours, and goals.
 - `learning_update_profile`: Update target role, weekly hours, learning pace, and preferences.
 - `learning_add_skill_evidence`: Record verifiable evidence for a skill.
 - `learning_get_skill_gaps`: Analyze current vs. target skills with DAG ordering.
 - `learning_generate_plan`: Generate a fully structured, hour-bounded learning plan.
 - `learning_get_active_plan`: Retrieve current multi-week plan.
 - `learning_get_today_tasks`: Get specific learning and practice tasks scheduled for today.
 - `learning_generate_practice`: Generate a tailored coding task with starter code and hints.
 - `learning_evaluate_practice`: Evaluate a practice submission and update mastery.
 - `learning_generate_project`: Produce a realistic capstone project specification.
 - `learning_complete_project`: Record project completion and award expert evidence.
 - `learning_get_struggles`: View active struggle topics and remedial actions taken.
 - `learning_get_progress`: Comprehensive progress summary across completed objectives.
 - `learning_list_target_roles`: View supported career paths and skill requirements.
 - `learning_list_skills`: Browse skill taxonomy and prerequisite relationships.
 - `learning_get_diagnostic_questions`: Get follow-up questions to fill profile gaps.
 - `learning_record_activity`: Log study sessions, reading, and self-directed practice.
 
 ### Adding New Skills and Target Roles
 
 Skills and roles can be registered dynamically via the `SkillEngine` or seeded in [lyra/learning/skill_engine.py](file:///Users/vikas/Desktop/Lyra/lyra/learning/skill_engine.py):
 
 ```python
 from lyra.learning.models import Skill, TargetRole, SkillLevel
 
 # Register a new skill with prerequisites
 skill_engine.register_skill(
     Skill(
         name="GraphQL",
         category="Backend",
         description="Declarative data querying language",
         prerequisites=["HTTP", "REST APIs"],
     )
 )
 
 # Register a new target role
 skill_engine.register_role(
     TargetRole(
         role_id="cloud_architect",
         title="Cloud Solutions Architect",
         description="Designs and deploys scalable cloud infrastructures.",
         required_skills={
             "Cloud Infrastructure": SkillLevel.ADVANCED,
             "Docker & Containerization": SkillLevel.ADVANCED,
             "Kubernetes": SkillLevel.INTERMEDIATE,
             "System Design": SkillLevel.ADVANCED,
         },
         elective_skills=["Terraform", "CI/CD Pipelines"],
     )
 )
 ```
 
---

## Anakin AI Integration & Workflow Engine

LYRA natively integrates **Anakin AI** as an intelligent provider and configuration-driven workflow execution layer. Anakin can operate both as a conversational/reasoning LLM provider and as a structured workflow runner executing specialized Quick Apps and Chatbots.

### Architecture & Separation of Reasoning from Execution

LYRA strictly separates cognitive reasoning from physical computer execution:

```text
VOICE / TEXT INPUT
       │
       ▼
   STT / INPUT
       │
       ▼
  INTENT ROUTER  ────────► Classifies command (OPEN_APP, WRITE_TEXT, PLAY_MEDIA, etc.)
       │
       ▼
  TASK PLANNER   ────────► Synthesizes Plan: tool call & parameters
       │
       ▼
┌─────────────────────────────┐
│    AI REASONING LAYER       │
│  Gemini / Anakin / Grok /   │
│  Groq / Ollama              │
└──────────────┬──────────────┘
               │
               ▼
         TOOL EXECUTOR   ────────► Executes REAL action (AppleScript, Filesystem, Browser, System)
               │
               ▼
         VERIFICATION    ────────► Verifies actual computer state (file exists, app running, text written)
               │
               ▼
            TTS / UI     ────────► "Done." / "Playing Believer." (Only confirmed upon verification)
```

- **Plan**: Establish the exact parameters (e.g. create directory `~/Desktop/AI/backend`, open Notes, set brightness).
- **Execute**: Perform real macOS automation, filesystem API call, or browser interaction.
- **Verify**: Confirm state programmatically. LYRA never says "Done" if an action failed.

---

### Anakin Configuration & Setup

Add the following environment variables to your `.env` file:

```bash
# Anakin AI Configuration
ANAKIN_API_KEY=your_anakin_api_key_here
ANAKIN_APP_ID=your_primary_app_id_here
ANAKIN_API_VERSION=2024-05-06
ANAKIN_APP_TYPE=quickapp # "quickapp" or "chatbot"
ANAKIN_BASE_URL=https://api.anakin.ai

# Provider Priority (Anakin is automatically routed based on task type)
PROVIDER_PRIORITY=gemini,anakin,groq,openrouter,cerebras,local
```

> [!IMPORTANT]
> **API Access & Credits Notice**: Anakin AI API calls require valid API credits or an active plan on your Anakin AI account. If credits are exhausted or an invalid App ID is supplied, LYRA's intelligent router automatically fails over to Gemini, Grok, or local Ollama.

#### Dynamic Workflow Configuration (`ANAKIN_WORKFLOWS`)

You can register custom Anakin Quick Apps as specialized LYRA tools by providing a JSON list in `ANAKIN_WORKFLOWS`:

```json
[
  {
    "name": "research_workflow",
    "app_id": "app_research_id",
    "description": "Researches a technical topic and produces deep structured summaries",
    "input_schema": {"topic": "string"}
  },
  {
    "name": "resume_analyzer",
    "app_id": "app_resume_id",
    "description": "Analyzes resumes against job requirements and highlights gaps",
    "input_schema": {"resume_text": "string"}
  }
]
```

When registered, the `IntentRouter` routes relevant user prompts (e.g., *"Lyra, research the best free Python resources"*) directly to the corresponding `AnakinWorkflowTool`.

---

### Task-Aware Provider Routing & Fallback

LYRA routes prompts based on task taxonomy:

| Task Type | Primary Provider | Fallback Chain |
| :--- | :--- | :--- |
| **General Conversation** | Gemini | Grok → Groq → Anakin → Ollama |
| **Complex Workflows / Research** | Anakin | Gemini → Grok → Ollama |
| **Private / Offline Operation** | Ollama (`local`) | None (Air-gapped) |
| **macOS & System Automation** | LYRA ToolExecutor | Real AppleScript / CoreGraphics / System |
| **Browser & Media Automation** | LYRA BrowserExecutor | Playwright / Accessibility DOM selectors |

---

### Real macOS & Browser Automation

LYRA performs real system operations on macOS. **No demo pages or simulated actions.**

#### 1. Voice & Natural Language Commands
- **Notes Automation**:
  - *"Lyra, open Notes and write Hello Boss."*
  - *"Lyra, create a note called Meeting and write today's agenda."*
  - *(Opens macOS Notes, targets or creates the note, injects text, and verifies content.)*
- **VS Code**:
  - *"Lyra, open VS Code."*
  - *"Lyra, open my project in VS Code."*
  - *"Lyra, create a Python file called main.py."*
- **Filesystem & Hierarchical Folders**:
  - *"Lyra, create a folder on my Desktop called AI Projects."*
  - *"Lyra, create this folder structure on my Desktop: AI/backend/frontend/data"*
- **Browser & YouTube**:
  - *"Lyra, open a new browser tab and search Google for Python internships."*
  - *"Lyra, open YouTube and play Believer."*
  - *(Navigates YouTube, locates the search result, triggers video playback, and verifies state.)*
- **System Controls**:
  - *"Lyra, increase brightness."* / *"Lyra, set brightness to 40 percent."*
  - *"Lyra, increase volume."* / *"Lyra, mute the Mac."*

---

### Required macOS Permissions

To enable real macOS and browser automation, grant the following permissions in **macOS System Settings → Privacy & Security**:

1. **Accessibility (`AXUIElement`)**:
   - Required for: Screen inspection, keyboard typing, window focusing, and system brightness/volume shortcuts.
   - Target: Terminal, iTerm2, or VS Code (whichever is executing `python main.py`).
2. **Automation / Apple Events**:
   - Required for: Controlling **Notes.app**, **System Events**, **Google Chrome**, and **Safari**.
   - macOS will prompt once upon first execution: click **Allow**.
3. **Microphone**:
   - Required for: Voice-first continuous listening mode (`python main.py`).
4. **Full Disk Access / Filesystem (Optional)**:
   - Required if managing files outside user's home directory.

---

### Troubleshooting

- **"Anakin API returned 401 / Unauthorized"**: Verify `ANAKIN_API_KEY` in `.env`. Ensure there are no surrounding whitespace characters or invalid prefixes.
- **"Anakin API returned 429 / Quota Exceeded"**: Your Anakin AI workspace plan has exceeded its rate limit or credit quota. LYRA will automatically route to Gemini or Ollama.
- **"Notes automation failed / permission denied"**: Open **System Settings → Privacy & Security → Automation** and ensure your Terminal application has checked permission for **Notes** and **System Events**.
- **"Browser could not click YouTube result"**: LYRA utilizes bounded retries across DOM selectors, accessibility tree selectors, and keyboard navigation (`Enter`). Ensure Chrome or default browser is not minimized behind a modal alert.

---

## Running the Test Suite

LYRA includes a comprehensive test suite of **559 unit and hardening tests**:

```bash
# Run complete test suite (all 559 tests)
pytest tests/unit/ -v

# Run Anakin Provider & Workflow tests specifically
pytest tests/unit/test_anakin_provider.py tests/unit/test_anakin_workflow_tool.py tests/unit/test_intent_router.py tests/unit/test_anakin_acceptance.py -v
```

---

## Running LYRA

To start the complete LYRA system in full voice-first mode:

```bash
python main.py
```

This single command initializes configuration, secret scrubbing, provider routing (Gemini, Anakin, Ollama), memory, tool registry, macOS & browser executors, speech-to-text, text-to-speech, intent classification, and the verification layer.

---

## License

LYRA is open-source software licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
# Lyra-
