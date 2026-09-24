import uuid
import asyncio
import sqlite3
import os
import sys
from pathlib import Path
from typing import Annotated,Any
from pydantic import BaseModel,Field,create_model
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage,HumanMessage,AIMessage,ToolMessage,SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph,START,END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt,Command
from mcp import Client,StdioServerParameters
from contextvars import ContextVar

current_user_id=ContextVar(
    "current_user_id",
    default=None
)


# MCP

current_workspace_path=ContextVar(
    "current_workspace_path",
    default=None
)

current_progress_callback=ContextVar(
    "current_progress_callback",
    default=None
)


def report_progress(message,**kwargs):

    callback=current_progress_callback.get()

    if callback is None:
        return

    progress={
        "message":message,
        **kwargs
    }

    try:
        callback(progress)
    except Exception:
        pass


def get_workspace_path(user_id):

    local_workspace=current_workspace_path.get()

    if local_workspace:
        workspace_path=os.path.abspath(
            os.path.expanduser(local_workspace)
        )

        if not os.path.isdir(workspace_path):
            raise FileNotFoundError(
                "Selected workspace folder does not exist."
            )

        return workspace_path

    conn=sqlite3.connect("auth.db")

    workspace=conn.execute(
        "SELECT workspace_path FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if workspace is None:
        raise ValueError("User not found.")

    if not workspace[0]:
        raise ValueError("No workspace selected for this user.")

    workspace_path=workspace[0]

    if not os.path.isdir(workspace_path):
        raise FileNotFoundError(
            "Selected workspace folder does not exist."
        )

    return workspace_path


def get_mcp_server(user_id):

    project_root=get_workspace_path(user_id)
    server_path=Path(__file__).resolve().parent/"mcp_server.py"

    if not server_path.is_file():
        raise FileNotFoundError("mcp_server.py was not found.")

    return StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env={
            **os.environ,
            "PROJECT_ROOT":project_root
        },
        cwd=project_root
    )

MCP_ERROR_PREFIX = "__MCP_ERROR_TYPE__:"


# CHANGE:
# MCP server agar tool error deta hai to SDK result.is_error=True karta hai.
# Error message ke marker se original Python exception type recover karenge.
def extract_mcp_result(result):
    data = getattr(result,"structured_content",None)

    if isinstance(data,dict) and "result" in data:
        data = data["result"]
    if data is not None:
        return data
    content = getattr(result,"content",None) or []
    texts = []

    for item in content:
        if hasattr(item,"text"):
            texts.append(item.text)
    if texts:
        return "\n".join(texts)

    return None


def process_mcp_result(result):
    data = extract_mcp_result(result)

    if data is None:
        return "Tool failed: Exception: MCP tool returned no result."

    if isinstance(data,str) and MCP_ERROR_PREFIX in data:
        error_data = data.split(MCP_ERROR_PREFIX,1)[1]
        error_name,error_message = error_data.split(":",1)
        return f"Tool failed: {error_name}: {error_message}"

    if result.is_error:
        return f"Tool failed: Exception: {data}"

    if isinstance(data,str):
        return data

    try:
        import json
        return json.dumps(data,ensure_ascii=False)
    except Exception:
        return str(data)


def get_runtime_user_id():

    user_id=current_user_id.get()

    if user_id is not None:
        return int(user_id)

    env_user_id=os.getenv("WORKSPACE_USER_ID")

    if env_user_id:
        return int(env_user_id)

    raise RuntimeError("User identity is missing.")


async def mcp_call_tool(tool_name,arguments):

    user_id=get_runtime_user_id()

    mcp_server=get_mcp_server(user_id)

    async with Client(mcp_server) as client:

        result=await client.call_tool(
            tool_name,
            arguments
        )

        return process_mcp_result(result)


def call_mcp_tool(tool_name,arguments):
    return asyncio.run(
        mcp_call_tool(tool_name,arguments)
    )


#===========================MCP DISCOVERY===========================

def get_mcp_server_for_discovery():
    project_root=Path(__file__).resolve().parent
    server_path=project_root/"mcp_server.py"

    return StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env={
            **os.environ,
            "PROJECT_ROOT":str(project_root)
        },
        cwd=str(project_root)
    )


async def discover_mcp_tools():
    discovered_tools = []
    cursor = None

    async with Client(get_mcp_server_for_discovery()) as client:
        while True:
            page = await client.list_tools(cursor=cursor)
            discovered_tools.extend(page.tools)

            if page.next_cursor is None:
                break

            cursor = page.next_cursor

    return discovered_tools

async def discover_mcp_resources():
    resources=[]
    cursor=None

    async with Client(get_mcp_server_for_discovery()) as client:
        while True:
            page=await client.list_resources(cursor=cursor)
            resources.extend(page.resources)

            if page.next_cursor is None:
                break

            cursor=page.next_cursor

    return resources


async def read_mcp_resource(uri):

    user_id=get_runtime_user_id()

    async with Client(get_mcp_server(user_id)) as client:
        result=await client.read_resource(uri)
        return result


#SCHEMA

# CHANGE:
# MCP ka JSON input schema LangChain ke Pydantic args schema mein convert karenge.
def schema_type(schema,name):
    if not isinstance(schema,dict):
        return Any
    if "enum" in schema:
        return str
    if "anyOf" in schema or "oneOf" in schema:
        return Any
    schema_kind = schema.get("type")
    if schema_kind == "string":
        return str
    if schema_kind == "integer":
        return int
    if schema_kind == "number":
        return float
    if schema_kind == "boolean":
        return bool
    if schema_kind == "array":
        item_type = schema_type(
            schema.get("items",{}),
            f"{name}Item"
        )
        return list[item_type]

    if schema_kind == "object":
        properties = schema.get("properties",{})
        required = set(schema.get("required",[]))
        fields = {}
        for field_name,field_schema in properties.items():
            field_type = schema_type(field_schema,f"{name}_{field_name}")
            description = field_schema.get("description")
            if field_name in required:
                default = Field(...,description=description) if description else ...
                fields[field_name] = (field_type,default)
            else:
                default = Field(None,description=description) if description else None
                fields[field_name] = (field_type | None,default)
        return create_model(name,**fields)

    return Any


def create_mcp_args_schema(tool_name,input_schema):
    if not isinstance(input_schema,dict):
        input_schema = {}

    return schema_type(
        {
            "type":"object",
            "properties":input_schema.get("properties",{}),
            "required":input_schema.get("required",[])
        },
        f"{tool_name.replace('-','_')}Input"
    )


#DYNAMIC TOOLS

def create_mcp_tool(mcp_tool):
    mcp_name = mcp_tool.name
    langchain_name = f"mcp_{mcp_name}"
    description = mcp_tool.description or f"MCP tool: {mcp_name}"

    input_schema = getattr(mcp_tool,"inputSchema",None)

    if input_schema is None:
        input_schema = getattr(mcp_tool,"input_schema",{})

    args_schema = create_mcp_args_schema(
        mcp_name,
        input_schema
    )

    def run_mcp_tool(**kwargs):
        return call_mcp_tool(
            mcp_name,
            kwargs
        )

    run_mcp_tool.__name__ = langchain_name
    run_mcp_tool.__doc__ = description

    return StructuredTool.from_function(
        func=run_mcp_tool,
        name=langchain_name,
        description=description,
        args_schema=args_schema
    )

mcp_tool_definitions=asyncio.run(discover_mcp_tools())

mcp_resources=asyncio.run(discover_mcp_resources())

print("\nMCP resources discovered:")

for resource in mcp_resources:
    print(f"- {resource.uri}")

print()



tools = []
for mcp_tool in mcp_tool_definitions:
    tool = create_mcp_tool(mcp_tool)
    tools.append(tool)

print("\nMCP tools discovered:")

for mcp_tool in mcp_tool_definitions:
    print(f"- mcp_{mcp_tool.name}")

print()


dangerous_tools = {
    "mcp_write_file",
    "mcp_edit_file",
    "mcp_command_run"
}

# PLANNER

planner_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

planner_groq = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0
)

planner_nvidia = ChatOpenAI(
    model="openai/gpt-oss-120b",
    temperature=0,
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)

#LLM

gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

groq = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0
)

nvidia = ChatOpenAI(
    model="openai/gpt-oss-120b",
    temperature=0,
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)

gemini = gemini.bind_tools(tools)
groq = groq.bind_tools(tools)
nvidia = nvidia.bind_tools(tools)


failed_providers=ContextVar(
    "failed_providers",
    default=None
)

def get_failed_providers():
    providers=failed_providers.get()

    if providers is None:
        providers=set()
        failed_providers.set(providers)

    return providers


def get_llm_response(messages):
    providers = [
        ("groq",groq),
        ("gemini",gemini),
        ("nvidia",nvidia)
    ]

    failed=get_failed_providers()

    for provider_name,llm in providers:
        if provider_name in failed:
            print(f"Skipping {provider_name}")
            continue

        try:
            return llm.invoke(messages)
        except Exception as e:
            print(f"{provider_name} failed: {e}")
            failed.add(provider_name)

    raise Exception("All LLM providers failed.")

# for planner
def get_planner_response(messages):

    providers = [
        ("groq",planner_groq),
        ("gemini",planner_gemini),
        ("nvidia",planner_nvidia)
    ]

    failed=get_failed_providers()

    for provider_name,llm in providers:
        if provider_name in failed:
            print(f"Skipping planner {provider_name}")
            continue

        try:
            return llm.invoke(messages)
        except Exception as e:
            print(f"Planner {provider_name} failed: {e}")
            failed.add(provider_name)

    raise Exception("All planner LLM providers failed.")

#STATE

class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage],add_messages]
    approval: str | None = None
    pending_tools: list[dict] = Field(default_factory=list)
    approved_tool: dict | None = None
    failed_tool_call: dict | None = None
    error_type: str | None = None
    retry_count: int = 0
    plan: list[str] = Field(default_factory=list)
    current_step: int = 0
    verification_result: str | None = None
    fix_attempts: int = 0
    verification_mode: bool = False

# planner agent
#===========================PLANNER================================

def planner(state:AgentState):

    system_message = SystemMessage(
        content="""
You are a coding task planner.

Create a concise step-by-step plan for completing the user's coding task.

The plan should normally cover:
1. Inspect the project and identify relevant files.
2. Read the relevant code.
3. Make the required changes.
4. Run appropriate tests or verification commands.
5. Fix failures if necessary.
6. Verify the final result.

Rules:
- Do not execute any tools.
- Do not write code.
- Only create the plan.
- Return one step per line.
- Start each step with a number.
- Do not commit, push, or modify git history unless the user explicitly asks.
- Do not add unnecessary steps that are not required by the user's task.
"""
    )

    response = get_planner_response(
        [system_message] + state.messages
    )
    content = str(response.content).strip()
    plan = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        elif line.startswith("* "):
            line = line[2:].strip()
        else:
            parts = line.split(".",1)
            if len(parts) == 2 and parts[0].isdigit():
                line = parts[1].strip()
            else:
                parts = line.split(")",1)
                if len(parts) == 2 and parts[0].isdigit():
                    line = parts[1].strip()
        if line:
            plan.append(line)
    if not plan:
        plan = [
            "Inspect the project and identify the relevant files.",
            "Read the relevant code.",
            "Make the required changes.",
            "Run appropriate tests or verification commands.",
            "Fix failures if necessary.",
            "Verify the final result."
        ]
    print("\n📋 Plan:")
    for index,step in enumerate(plan,start=1):
        print(f"{index}. {step}")
    print()

    report_progress(
        "Plan created.",
        plan=plan
    )

    return {
        "plan":plan,
        "current_step":0
    }

#AGENT

def agent(state:AgentState):

    plan_text = "\n".join(
        f"{index}. {step}"
        for index,step in enumerate(
            state.plan,
            start=1
        )
    )
    verification_text = state.verification_result or "Not verified yet."

    system_message = SystemMessage(
        content=f"""
You are a coding agent.

The MCP tools are discovered dynamically from the MCP server.
Use the appropriate MCP tool for the user's request.

For file operations:
- use mcp_list_files to inspect project files
- use mcp_read_file to read a file
- use mcp_write_file to create or overwrite a file
- use mcp_edit_file to modify an existing file
- use mcp_command_run to run terminal commands

When the user asks you to create, write, modify, or save code in a file,
MUST use the appropriate MCP file tool instead of only replying with code.

If mcp_read_file reports FileNotFoundError for a file,
use mcp_list_files to verify the project contents before concluding that
the requested file does not exist.

If a tool reports that an operation was rejected by the security policy,
do not retry the same operation and do not use another tool to bypass it.

If a tool succeeds, do not repeat the same operation unless the user asks.

If a tool fails, analyze the error before the next action.
Do not blindly repeat the failed tool call.

================ CURRENT PLAN ================

{plan_text}

===============VERIFICATION RESULT ================
{verification_text}

Use the plan as guidance while completing the task.

If verification failed, analyze the verification failure,
identify what needs to be fixed, use the appropriate MCP tools,
and then make the required changes.
"""
    )

    recent_messages = state.messages[-12:]

    report_progress(
        "Agent is analyzing the task.",
        plan=state.plan,
        verification_result=state.verification_result
    )

    response = get_llm_response(
        [system_message] + recent_messages
    )
    return {
        "messages":[response]
    }


#TOOL FLOW

def classify_tools(state:AgentState):

    last_message = state.messages[-1]
    pending_tools=last_message.tool_calls

    if pending_tools:
        report_progress(
            "Tool call requested.",
            tool_calls=[
                {
                    "name":tool_call["name"],
                    "args":tool_call.get("args",{})
                }
                for tool_call in pending_tools
            ]
        )

    return {
        "pending_tools":pending_tools
    }


def should_continue(state:AgentState):

    if not state.pending_tools:
        return END
    next_tool = state.pending_tools[0]["name"]
    if (state.verification_mode and next_tool == "mcp_command_run"):
        return "process"
    if next_tool in dangerous_tools:
        return "approval"
    return "process"


def human_approval(state:AgentState):

    tool_call=state.pending_tools[0]

    approval_request=(
        f"Approval required\n"
        f"Tool: {tool_call["name"]}\n"
        f"Arguments:\n{tool_call["args"]}"
    )

    report_progress(
        "Approval required.",
        tool=tool_call["name"],
        approval_request=approval_request
    )

    approval=interrupt(approval_request)

    return {
        "approval":approval
    }


def process_approval(state:AgentState):

    tool_call = state.pending_tools[0]

    if (state.verification_mode and tool_call["name"] == "mcp_command_run"):
        return {
            "approved_tool":tool_call,
            "pending_tools":state.pending_tools[1:]
        }
    if tool_call["name"] not in dangerous_tools:
        return {
            "approved_tool":tool_call,
            "pending_tools":state.pending_tools[1:]
        }
    if state.approval == "yes":
        return {
            "approved_tool":tool_call,
            "pending_tools":state.pending_tools[1:],
            "approval":None
        }
    rejection_message = ToolMessage(
        content=(
            f"The user rejected the execution of the tool "
            f"'{tool_call['name']}'. Do not execute this tool call."
        ),
        tool_call_id=tool_call["id"]
    )
    return {
        "approved_tool":None,
        "pending_tools":state.pending_tools[1:],
        "approval":None,
        "messages":[rejection_message]
    }


def after_process(state:AgentState):

    if state.approved_tool:
        return "execute"
    if state.pending_tools:
        next_tool = state.pending_tools[0]["name"]
        if (
            state.verification_mode
            and next_tool == "mcp_command_run"
        ):
            return "process"
        if next_tool in dangerous_tools:
            return "approval"
        return "process"
    return "agent"


def execute_approved_tool(state:AgentState):

    tool_call=state.approved_tool

    report_progress(
        "Executing approved tool.",
        tool=tool_call["name"],
        args=tool_call.get("args",{})
    )

    return {
        "messages":[
            AIMessage(
                content="",
                tool_calls=[tool_call]
            )
        ],
        "approved_tool":None
    }


#ERROR / RETRY

def classify_error(error:Exception)->str:

    if isinstance(error,(TimeoutError,ConnectionError)):
        return "retry"
    if isinstance(error,(FileNotFoundError,PermissionError,IsADirectoryError)):
        return "agent"
    return "stop"


def retry_tool(state:AgentState):
    return {
        "messages":[
            AIMessage(
                content="",
                tool_calls=[state.failed_tool_call]
            )
        ],
        "failed_tool_call":None,
        "error_type":None
    }


def check_tool_result(state:AgentState):

    last_message=state.messages[-1]
    if isinstance(last_message,ToolMessage):
        content=str(last_message.content)
        failed_tool_call=None
        for message in reversed(state.messages):
            if isinstance(message,AIMessage):
                for tool_call in message.tool_calls:
                    if tool_call["id"]==last_message.tool_call_id:
                        failed_tool_call=tool_call
                        break
            if failed_tool_call:
                break

        tool_name=failed_tool_call["name"] if failed_tool_call else None

        if content.startswith("Tool failed:"):
            report_progress(
                "Tool failed.",
                tool=tool_name,
                error=content
            )

            parts=content.split(":",2)
            error_name=parts[1].strip() if len(parts)>1 else "Exception"
            error_classes={
                "TimeoutError":TimeoutError,
                "ConnectionError":ConnectionError,
                "FileNotFoundError":FileNotFoundError,
                "PermissionError":PermissionError,
                "IsADirectoryError":IsADirectoryError
            }
            error=error_classes.get(error_name,Exception)()
            decision=classify_error(error)

            if decision=="retry":
                if state.retry_count<3:
                    return {
                        "error_type":"retry",
                        "retry_count":state.retry_count+1,
                        "failed_tool_call":failed_tool_call
                    }
                return {"error_type":"stop"}
            return {"error_type":decision}
        
        if state.verification_mode:
            report_progress(
                "Verification tool completed.",
                tool=tool_name,
                result=content
            )
            return {
                "error_type":None,
                "retry_count":0,
                "failed_tool_call":None,
                "verification_mode":True
            }
        if failed_tool_call:
            tool_name=failed_tool_call["name"]
            if state.pending_tools:
                return {
                    "error_type":None,
                    "retry_count":0,
                    "failed_tool_call":None
                }
            if tool_name in {"mcp_write_file","mcp_edit_file"}:
                return {
                    "error_type":None,
                    "retry_count":0,
                    "failed_tool_call":None,
                    "verification_mode":True
                }
            
    return {
        "error_type":None,
        "retry_count":0,
        "failed_tool_call":None
    }

# verifier

def verifier(state:AgentState):

    report_progress(
        "Verifying the result.",
        plan=state.plan,
        fix_attempts=state.fix_attempts
    )

    if state.verification_mode:
        last_message=state.messages[-1]
        if isinstance(last_message,ToolMessage):
            tool_call_id=last_message.tool_call_id
            verification_tool=False

            for message in reversed(state.messages):
                if isinstance(message,AIMessage):
                    for tool_call in message.tool_calls:
                        if tool_call["id"]==tool_call_id:
                            if tool_call["name"] in {
                                "mcp_list_files",
                                "mcp_read_file",
                                "mcp_command_run"
                            }:
                                verification_tool=True
                            break
                if verification_tool:
                    break

            if verification_tool:

                content=str(last_message.content)

                if content.startswith("Tool failed:"):
                    return {
                        "messages":[
                            AIMessage(
                                content=f"FAIL: {content}"
                            )
                        ],
                        "verification_result":f"FAIL: {content}"
                    }

                if any(
                    indicator in content
                    for indicator in [
                        "failed",
                        "error",
                        "errors",
                        "failure",
                        "FAILED"
                    ]
                ):
                    return {
                        "messages":[
                            AIMessage(
                                content=f"FAIL: {content}"
                            )
                        ],
                        "verification_result":f"FAIL: {content}"
                    }

                return {
                    "messages":[
                        AIMessage(
                            content=f"PASS: {content}"
                        )
                    ],
                    "verification_result":f"PASS: {content}"
                }

    system_message=SystemMessage(
        content="""
You are a coding task verifier.

Your job is to verify whether the user's requested coding task
has actually been completed.

You may use these MCP tools for verification:
- mcp_list_files
- mcp_read_file
- mcp_command_run

You must NOT use:
- mcp_write_file
- mcp_edit_file

Run exactly one appropriate non-destructive verification command.
After running a verification command, do not run another verification command.

Once a verification result is available:
- analyze it
- do not run the same verification command again
- return exactly:

PASS: <brief reason>

or

FAIL: <brief reason>
"""
    )

    response=get_llm_response(
        [system_message]+state.messages[-12:]
    )

    return {
        "messages":[response]
    }

def after_tool_result(state:AgentState):

    if state.error_type == "retry":
        return "retry_tool"
    if state.error_type == "agent":
        return "agent"
    if state.verification_mode:
        return "verifier"
    if state.error_type in [None,"stop"]:
        return "verifier"
    return END

def after_verifier(state:AgentState):

    last_message = state.messages[-1]
    if isinstance(last_message,AIMessage):
        if last_message.tool_calls:
            return "tools"
        content = str(
            last_message.content
        ).strip()
        if content.startswith("PASS:"):
            return END
        if content.startswith("FAIL:"):
            if state.fix_attempts < 3:
                return "fix"
            return END
    return END

def fix(state:AgentState):

    report_progress(
        "Fixing the verification failure.",
        attempt=state.fix_attempts+1
    )

    return {
        "fix_attempts":state.fix_attempts + 1,
        "verification_mode":False
    }

def handle_tool_error(error:Exception)->str:
    return f"Tool failed: {type(error).__name__}: {str(error)}"


#GRAPH

tool_node = ToolNode(
    tools,
    handle_tool_errors=handle_tool_error
)

conn = sqlite3.connect(
    "checkpoints.db",
    check_same_thread=False
)

memory = SqliteSaver(conn)

graph = StateGraph(AgentState)

graph.add_node("planner",planner)
graph.add_node("agent",agent)
graph.add_node("verifier",verifier)
graph.add_node("fix",fix)
graph.add_node("tool",tool_node)
graph.add_node("approval",human_approval)
graph.add_node("classify_tools",classify_tools)
graph.add_node("process_approval",process_approval)
graph.add_node("execute_approved_tool",execute_approved_tool)
graph.add_node("check_tool_result",check_tool_result)
graph.add_node("retry_tool",retry_tool)

graph.add_edge(START,"planner")
graph.add_edge("planner","agent")
graph.add_edge("agent","classify_tools")

graph.add_conditional_edges(
    "classify_tools",
    should_continue,
    {
        "approval":"approval",
        "process":"process_approval",
        END:END
    }
)

graph.add_edge("approval","process_approval")

graph.add_conditional_edges(
    "process_approval",
    after_process,
    {
        "execute":"execute_approved_tool",
        "approval":"approval",
        "process":"process_approval",
        "agent":"agent"
    }
)
graph.add_edge("execute_approved_tool","tool")
graph.add_edge("tool","check_tool_result")
graph.add_conditional_edges(
    "check_tool_result",
    after_tool_result,
    {
        "retry_tool":"retry_tool",
        "agent":"agent",
        "verifier":"verifier",
        END:END
    }
)
graph.add_conditional_edges(
    "verifier",
    after_verifier,
    {
        "tools":"classify_tools",
        "fix":"fix",
        END:END
    }
)
graph.add_edge("fix","agent")
graph.add_edge("retry_tool","classify_tools")
app = graph.compile(checkpointer=memory)

#=============================================================

def make_thread_key(user_id,thread_id):
    return f"user:{user_id}:thread:{thread_id}"


def build_input_data(user_input):
    return {
        "messages":[
            HumanMessage(content=user_input)
        ],
        "approval":None,
        "pending_tools":[],
        "approved_tool":None,
        "failed_tool_call":None,
        "error_type":None,
        "retry_count":0,
        "plan":[],
        "current_step":0,
        "verification_result":None,
        "fix_attempts":0,
        "verification_mode":False
    }


def get_last_response(config):
    state=app.get_state(config)
    messages=state.values.get("messages",[])

    for message in reversed(messages):
        if isinstance(message,AIMessage):
            if message.tool_calls:
                continue

            if message.content:
                return str(message.content)

    return ""
def run_agent(
    user_id,
    thread_id=None,
    user_input=None,
    approval=None,
    workspace_path=None,
    progress_callback=None
):

    user_id=int(user_id)

    runtime_user_id=os.getenv("WORKSPACE_USER_ID")
    runtime_workspace=os.getenv("PROJECT_ROOT")

    workspace_token=None
    progress_token=None

    if workspace_path is not None:
        workspace_token=current_workspace_path.set(
            workspace_path
        )

    runtime_workspace_path=get_workspace_path(user_id)

    os.environ["WORKSPACE_USER_ID"]=str(user_id)
    os.environ["PROJECT_ROOT"]=runtime_workspace_path

    if progress_callback is not None:
        progress_token=current_progress_callback.set(
            progress_callback
        )

    try:
        get_workspace_path(user_id)

        if thread_id is None:
            thread_id=str(uuid.uuid4())

        config={
            "configurable":{
                "thread_id":make_thread_key(user_id,thread_id)
            }
        }

        user_token=current_user_id.set(user_id)
        provider_token=failed_providers.set(set())

        try:
            if approval is not None:
                input_data=Command(resume=approval)
            elif user_input is not None:
                input_data=build_input_data(user_input)
            else:
                raise ValueError("Either user_input or approval is required.")

            interrupted=False
            approval_request=None

            for chunk in app.stream(
                input_data,
                config=config,
                stream_mode=["messages","updates"]
            ):
                mode,data=chunk

                if mode != "updates":
                    continue

                if "__interrupt__" in data:
                    interrupted=True
                    interrupt_data=data["__interrupt__"][0]
                    approval_request=str(interrupt_data.value)

            response=get_last_response(config)
            state=app.get_state(config)

            return {
                "thread_id":thread_id,
                "response":response,
                "approval_required":interrupted,
                "approval_request":approval_request,
                "plan":state.values.get("plan",[])
            }

        finally:
            failed_providers.reset(provider_token)
            current_user_id.reset(user_token)

    finally:

        if runtime_user_id is None:
            os.environ.pop("WORKSPACE_USER_ID",None)
        else:
            os.environ["WORKSPACE_USER_ID"]=runtime_user_id

        if runtime_workspace is None:
            os.environ.pop("PROJECT_ROOT",None)
        else:
            os.environ["PROJECT_ROOT"]=runtime_workspace

        if workspace_token is not None:
            current_workspace_path.reset(workspace_token)

        if progress_token is not None:
            current_progress_callback.reset(progress_token)
