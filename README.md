AI Coding Agent

An AI-powered coding assistant that can understand a software task, create a plan, inspect a project, read and modify files, run approved project commands, verify the result, and maintain conversational context.

The project combines Streamlit, FastAPI, LangGraph, MCP, multiple LLM providers, SQLite, JWT authentication, OTP-based email verification, human approval, progress tracking, and a Local Agent bridge.

Current project model: the web UI and API can be deployed to the cloud, while local_agent.py runs on the user's own computer and performs the actual coding work inside the selected local workspace.

✨ What This Project Does

The Coding Agent is designed to work more like a practical software-development assistant than a simple chatbot.

A user can send a request such as:

Create a FastAPI project with authentication, a health-check endpoint,
and a requirements.txt file.

The system can then:

Understand the request.

Generate a concise implementation plan.

Inspect the selected project workspace.

Decide which MCP tools are required.

Ask for human approval before dangerous operations.

Create or edit project files.

Run permitted commands such as Python, pytest, npm, Git inspection commands, etc.

Report progress back to the UI.

Return the result and the files that changed.

Keep the conversation associated with a thread so that the user can continue working on the same task.

🏗️ Architecture

                         USER
                           │
                           ▼
                 ┌──────────────────┐
                 │   Streamlit UI   │
                 │  Chat + History  │
                 └────────┬─────────┘
                          │ HTTPS
                          ▼
                 ┌──────────────────┐
                 │   FastAPI API    │
                 │ Auth + Task API  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │     SQLite       │
                 │ users + tasks    │
                 └────────┬─────────┘
                          │
                    task polling
                          │
                          ▼
               ┌──────────────────────┐
               │    Local Agent       │
               │  local_agent.py      │
               │  user's computer     │
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐
               │      LangGraph       │
               │ Planner + Agent +    │
               │ Verification + HITL │
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐
               │         MCP          │
               │ Tools / Resources /  │
               │ Prompts              │
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐
               │ Selected Workspace   │
               │ User's real files    │
               └──────────────────────┘

Why is there a Local Agent?

A cloud server cannot directly manipulate arbitrary files on a user's personal computer.

The Local Agent solves this by running on the user's own machine. It authenticates with the FastAPI backend, waits for tasks, executes the LangGraph agent locally, and reports progress/results back to the server.

This means the final execution path is:

Cloud request
    ↓
FastAPI task
    ↓
Local Agent on user's computer
    ↓
LangGraph
    ↓
MCP
    ↓
User-selected local project folder

🧩 Main Components

1. Streamlit UI — streamlit_app.py

The frontend of the application.

It provides:

Login

Registration

OTP verification

Workspace display

Folder selection UI

Chat interface

Chat history

New chat

Logout

Agent progress

Plan display

Tool activity display

Approval requests

Created files

Modified-file diffs

Deleted-file information

Current file/code display where supported by the UI

The UI sends authenticated requests to FastAPI and waits for the Local Agent to process the created task.

2. FastAPI Backend — api.py

The backend manages authentication, users, workspace metadata, task creation, task status, progress, results, chat history, and approval requests.

Important responsibilities:

Create user accounts

Verify OTP

Authenticate users

Issue JWT access tokens

Store the selected workspace path

Create coding-agent tasks

Allow the Local Agent to claim pending tasks

Store task progress

Store task results

Track task status

Serve chat history

Handle human approval requests

Current task lifecycle

pending
   ↓
running
   ↓
 ┌─────────────────────────┐
 │                         │
 ▼                         ▼
completed            awaiting_approval
                          │
                          ▼
                       approve
                          │
                          ▼
                      completed

A task can also move to:

failed

3. Authentication — auth.py

Authentication is implemented using:

SQLite

pwdlib with Argon2 password hashing

JWT access tokens

HTTP Bearer authentication

Email OTP verification using Resend

Current authentication flow

Register
   ↓
Generate OTP
   ↓
Send OTP email
   ↓
Verify OTP
   ↓
Login
   ↓
JWT access token
   ↓
Authenticated API requests

Current token configuration

The current code creates JWT access tokens with a 30-minute expiry.

OTP

The current registration flow generates a 6-digit OTP and gives it a 5-minute validity window.

4. Agent Workflow — graph.py

This is the core AI reasoning and execution workflow.

The project uses LangGraph StateGraph and a Pydantic-based AgentState.

The graph contains state for things such as:

messages

approval state

pending tools

approved tool

failed tool call

error type

retry count

plan

current step

verification result

fix attempts

verification mode

High-level workflow

User Task
   ↓
Planner
   ↓
Coding Agent
   ↓
Classify Tool Call
   ↓
Human Approval when required
   ↓
Execute MCP Tool
   ↓
Verify Result
   ↓
Retry / Fix if necessary
   ↓
Final Response

The graph also reports progress through a callback so that the Local Agent can send live task information back to FastAPI.

🧠 LLM Provider Setup

The project is structured with provider fallback support.

Current provider integrations include:

Groq using ChatGroq

Google Gemini using ChatGoogleGenerativeAI

NVIDIA using ChatOpenAI with the NVIDIA API endpoint

The current configured model family in the code is:

Gemini:
gemini-2.5-flash

Groq:
openai/gpt-oss-120b

NVIDIA:
openai/gpt-oss-120b

The application tries providers in a defined order and skips providers that have already failed during the current execution context.

🔌 MCP Integration

The project uses the Python MCP SDK and a dedicated MCP server in:

mcp_server.py

The agent dynamically discovers MCP tools and exposes them to the LangGraph/LangChain agent as structured tools.

Current MCP tools

list_files

Lists files and folders in the current project directory.

read_file

Reads the complete content of a project file.

write_file

Creates or overwrites a file.

edit_file

Replaces a specified piece of text in an existing file.

command_run

Runs a permitted terminal command in the current project directory.

add_numbers

A small example utility tool used for MCP/tool-calling demonstrations.

test_retry_error

A test tool used to exercise retry/error handling.


The agent also treats file-writing and command execution operations as dangerous tools and can request human approval before execution.

🙋 Human-in-the-Loop Approval

The agent contains an approval mechanism using LangGraph interrupts.

When a dangerous operation needs confirmation, the workflow can pause and send an approval request to the UI.

Example:

Agent wants to modify:
main.py

[Approve]   [Reject]

The UI sends the approval decision back to the API, which creates an approval task. The Local Agent then resumes the agent workflow.

📁 Workspace Model

Every authenticated user has a workspace path associated with their account.

Example:

/Users/ritikmishra/Documents/pro

The Local Agent selects the real folder on the user's machine and sends the selected path to the backend through the workspace API.

The agent execution receives this workspace path and uses it as the project working directory.

Important

The workspace path is a path on the user's computer, not a path on the cloud server.

For example:

User A
/Users/aman/Desktop/project1

User B
/Users/rahul/Documents/project2

Each Local Agent works with the workspace belonging to its authenticated user.

💬 Chat History

Chats are associated with a thread_id.

This allows the user to continue a previous conversation and preserve the relationship between messages and agent tasks.

The UI provides:

Chat history list

Opening a previous chat

New chat

Workspace-aware history display

📡 Backend API

Important API routes currently used by the application include:

Authentication

Method

Endpoint

Purpose

POST

/auth/register

Create a new account and send OTP

POST

/auth/verify-otp

Verify email OTP

POST

/auth/login

Login and receive JWT

GET

/auth/me

Get the authenticated user

Workspace

Method

Endpoint

Purpose

POST

/workspace/select

Save the user's selected workspace

GET

/workspace

Read the current workspace

Agent

Method

Endpoint

Purpose

POST

/agent/chat

Create a coding-agent chat task

GET

/agent/task/{task_id}

Read task status/progress/result

POST

/agent/approve

Submit human approval/rejection

GET

/agent/chats

Read chat history

GET

/agent/chats/{thread_id}

Open a particular chat

Local Agent

Method

Endpoint

Purpose

GET

/local-agent/tasks/next

Claim the next pending task for the authenticated user

POST

/local-agent/tasks/{task_id}/progress

Upload progress/events

POST

/local-agent/tasks/{task_id}/result

Upload final result or failure

🗂️ Project Structure

A typical project structure is:

coding-agent/
│
├── api.py
├── auth.py
├── graph.py
├── mcp_server.py
├── local_agent.py
├── streamlit_app.py
│
├── requirements.txt
├── requirements-api.txt
├── render.yaml
├── .gitignore
├── DEPLOY.md
└── README.md

Runtime-generated files may include local SQLite/configuration files such as:

auth.db
checkpoints.db
.coding_agent/

These should not be committed to Git.

💻 Local Development Setup

Prerequisites

The current Local Agent's folder picker uses macOS osascript, so the existing local-folder workflow is currently designed around macOS.

You should have:

Python 3.12 or compatible Python version

Git

A virtual environment

API keys for the LLM providers you intend to use

A Resend API key for email OTP

1. Clone the Repository

git clone <YOUR_GITHUB_REPOSITORY_URL>
cd coding-agent

2. Create a Virtual Environment

python3 -m venv .venv

Activate it:

source .venv/bin/activate

3. Install Dependencies

For the full local application:

pip install -r requirements.txt

For the API-only environment:

pip install -r requirements-api.txt

🔐 Environment Variables

Create a local .env file in the project root.

A typical configuration is:

JWT_SECRET_KEY=your-strong-random-secret
RESEND_API_KEY=your-resend-api-key
GOOGLE_API_KEY=your-google-api-key
GROQ_API_KEY=your-groq-api-key
NVIDIA_API_KEY=your-nvidia-api-key

Use only the provider keys that your chosen configuration actually requires.

Never commit .env

The repository .gitignore should include:

.env
*.db
__pycache__/
.venv/
.cenv/
.coding_agent/

▶️ Run the Project Locally

The recommended local development setup has three logical pieces:

FastAPI
Streamlit
Local Agent

Terminal 1 — FastAPI

uvicorn api:app --reload

The API will normally be available at:

http://127.0.0.1:8000

FastAPI docs:

http://127.0.0.1:8000/docs

Terminal 2 — Streamlit

streamlit run streamlit_app.py

The Streamlit UI will normally open at a local Streamlit URL shown by the command.

Terminal 3 — Local Agent

python local_agent.py

The Local Agent will:

Load its saved configuration if one exists.

Validate the saved login token.

Ask for login again when necessary.

Check/select the user's workspace.

Poll the FastAPI backend for pending tasks.

Execute tasks through graph.py.

Send progress updates.

Send the final result back to FastAPI.

The Local Agent keeps its local configuration under:

~/.coding_agent/config.json

🔄 Example End-to-End Request

Suppose the user has selected:

/Users/username/Documents/my-project

The user sends:

Create a Python file called hello.py that prints Hello World.

The flow is approximately:

Streamlit
   │
   │ POST /agent/chat
   ▼
FastAPI
   │
   │ create task = pending
   ▼
SQLite
   │
   │ Local Agent polls
   ▼
Local Agent
   │
   │ run_agent(...)
   ▼
LangGraph
   │
   ▼
MCP
   │
   ▼
write_file("hello.py", ...)
   │
   ▼
Local project folder
   │
   ▼
hello.py created
   │
   ▼
Local Agent reports result
   │
   ▼
FastAPI
   │
   ▼
Streamlit
   │
   ▼
User sees result + changed file

📈 Progress and Activity Tracking

The UI can display information such as:

Current plan

Agent activity/events

Tool name

Tool arguments

Code that is about to be written

Old and new code for edits

Commands that were requested

Approval requests

Errors

Files created

Files modified

Files deleted

Diffs

This makes the agent's execution more transparent than a simple final-text chatbot.

🧪 Error Handling and Reliability

The project includes several reliability mechanisms:

Provider fallback

If one configured LLM provider fails, the agent can move to another configured provider.

Tool error handling

MCP errors are converted into structured tool errors so that the agent can reason about tool failures.

Retry handling

The LangGraph state tracks retry-related information and supports retry/fix flows for recoverable failures.

Verification

The workflow contains verification state and can attempt fixes when a generated change does not pass the expected verification path.

Task ownership

Task API queries are tied to the authenticated user, so users retrieve only their own tasks.

🚀 Deployment

The planned deployment architecture is:

Streamlit Community Cloud
        │
        ▼
FastAPI on Render
        │
        ▼
Task database
        │
        ▼
Local Agent on user's computer

FastAPI on Render

Use:

Build Command:
pip install -r requirements-api.txt

Start Command:
uvicorn api:app --host 0.0.0.0 --port $PORT

Configure the required environment variables in Render instead of committing secrets to Git.

The repository includes render.yaml for the API service configuration.

Streamlit Cloud

Deploy:

streamlit_app.py

The deployed Streamlit app needs the FastAPI service URL.

Recommended configuration:

API_URL=https://YOUR-RENDER-API.onrender.com

Do not hard-code API secrets into streamlit_app.py.

Local Agent with a deployed backend

When the API is deployed, the Local Agent must point to the deployed API instead of:

http://127.0.0.1:8000

The Local Agent still runs on the user's computer because that is where the real project files exist.

⚠️ Current Deployment Limitation

The current project is an MVP/portfolio architecture, not yet a fully packaged commercial desktop product.

Today, the user may need to run:

python local_agent.py

manually on their computer.

A future version can package the Local Agent as a desktop application/installer and provide a smoother flow such as:

Login
  ↓
Connect Computer
  ↓
Open Local Agent
  ↓
Select Folder
  ↓
Connected
  ↓
Chat

That is intentionally outside the current MVP deployment scope.

🗄️ SQLite and Production Persistence

The current application uses SQLite for:

User accounts

Workspace metadata

Agent tasks

Chat/task state

LangGraph checkpoints where configured

SQLite is convenient for local development and a portfolio MVP.

For a production multi-user deployment, persistent managed storage such as PostgreSQL should be considered so that authentication and application data survive service restarts/redeployments and can scale independently.

🔒 Security Notes

The project uses several security-oriented mechanisms:

Password hashing with Argon2 through pwdlib

JWT authentication

Authenticated task access

OTP verification

Explicit command allow-list

Human approval for dangerous operations

Project workspace restrictions in the MCP/file execution path

.env excluded from Git

Runtime/database files excluded from Git

Important production hardening still recommended

Before treating the project as a production service, consider adding:

Refresh tokens / session renewal

Better token expiry UX

Persistent PostgreSQL storage

Rate limiting

Stronger audit logging

More restrictive command policies

Per-user agent connection/heartbeat tracking

Desktop-agent packaging and signed installers

Better secret management

More robust sandboxing for arbitrary code execution

Automated tests and CI/CD

🛠️ Troubleshooting

Cannot connect to API

Check that FastAPI is running and that the Local Agent/Streamlit API URL is correct.

Local API example:

http://127.0.0.1:8000

Deployed example:

https://your-api.onrender.com

Invalid or expired token

The current JWT access token expires after 30 minutes.

Login again when the token has expired.

Local Agent keeps waiting

Check:

FastAPI is running.

The Local Agent is logged in.

The Local Agent is connected to the correct API URL.

A workspace has been selected.

The task appears for the authenticated user.

The Local Agent process is still running.

Workspace not found

The selected local folder must still exist on the user's computer.

A path stored on the server does not mean the cloud server itself has access to that folder.

OTP problems

Check:

RESEND_API_KEY

Email address

OTP expiry

Resend configuration

The current OTP is valid for 5 minutes.

🧑‍💻 Example User Experience — Current MVP

First-time user

1. Open website
2. Register
3. Receive OTP
4. Verify OTP
5. Login
6. Start local_agent.py on their computer
7. Login in Local Agent
8. Select project folder
9. Keep Local Agent running
10. Use the Streamlit chat

Returning user

The Local Agent saves its configuration locally, so on subsequent launches it can reuse the stored API URL, token, user ID, and workspace information when those values are still valid.

📦 Requirements Files

requirements.txt

Used for the complete application environment, including:

FastAPI

Uvicorn

Streamlit

Requests

LangChain integrations

LangGraph

SQLite checkpoint integration

MCP

Authentication/email dependencies

requirements-api.txt

Used for the backend deployment and contains the API/authentication dependencies needed by FastAPI.

📌 Current Project Status

Implemented

Streamlit UI

FastAPI backend

User registration

Email OTP verification

JWT authentication

Workspace selection/storage

Chat threads/history

Task queue

Local Agent

LangGraph agent workflow

MCP client/server integration

Dynamic MCP tool discovery

MCP resources/prompts

File read/write/edit tools

Command execution allow-list

Human approval flow

Progress reporting

File change/diff reporting

Multi-provider LLM fallback

Retry/error-handling paths

Future

Desktop Local Agent installer

One-click computer connection

Automatic startup/background agent

Token refresh flow

Persistent production database

Stronger sandboxing

Automated test suite

CI/CD

RAG and project-wide semantic search

More advanced agent memory

Richer IDE-style interface

🎯 Why This Project Is Interesting

This project demonstrates more than simple LLM prompting.

It combines:

LLMs
+ Tool Calling
+ LangGraph
+ MCP
+ Authentication
+ Human-in-the-Loop
+ Task Queues
+ Local File Execution
+ Multi-Provider Fallback
+ Verification / Retry
+ Web UI
+ API Backend

That makes it a strong practical example of an agentic AI coding system rather than a basic chatbot wrapper.

📄 License

Add your preferred license here, for example:

MIT License

Do not claim a license that has not actually been added to the repository. When you choose one, add the corresponding LICENSE file to the project.

👤 Author

Ritik Mishra

Built as an AI/GenAI engineering project using Python and modern agentic-AI tooling.

⭐ Final Note

The current goal of the project is to provide a working coding-agent MVP that can be deployed to the cloud while still performing actual file operations on the user's local machine through the Local Agent.

The architecture is intentionally modular so that the Local Agent can later evolve from a Python script into a polished desktop application without replacing the core LangGraph + MCP + FastAPI architecture.