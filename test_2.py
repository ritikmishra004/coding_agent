import uuid
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage,HumanMessage,AIMessage, ToolMessage, SystemMessage
from pathlib import Path
from langgraph.graph import StateGraph,START,END
from typing import Annotated
from pydantic import BaseModel,Field
import subprocess
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
import os
from langgraph.types import interrupt, Command

@tool
def list_files()->list[str]:
    "List all files and folder in the current project directory"
    files = []
    for path in Path(".").iterdir():
        if path.name in [".cenv", "__pycache__", ".git", ".env","checkpoints.db"]:
            continue
        else:
            files.append(path.name)
    return files

@tool 
def read_file(file_path: str) -> str:
    """Read the complete contents of a file."""
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} is not a file."
    return path.read_text()

@ tool 
def write_file(file_path:str,content:str)->str:
    """Create or overwrite a file with the provided content."""
    with open(file_path,"w")as file:
        file.write(content)
    return f"{file_path} created successfully."

@tool
def edit_file(file_path,old_text,new_text):
    """Replace specific existing text in a file with new text."""
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} is not a file."
    content = path.read_text()
    if old_text not in content:
        return f"{file_path} text not found in it"
    content = content.replace(old_text,new_text,1)
    path.write_text(content)
    return f"{file_path} updated successfully"

@tool
def command_run(command):
    """Run a terminal command in the current project directory."""
    result = subprocess.run(
        command,
        shell = True,
        capture_output=True,
        text = True
    )
    return result.stdout + result.stderr


#===========================tools======================================
tools =[
    list_files,
    read_file,
    write_file,
    edit_file,
    command_run
]
#===========================LLM======================================
gemini = ChatGoogleGenerativeAI(
    model = "gemini-2.5-flash",
    temperature = 0
)
groq = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0
)
nvidia=ChatOpenAI(
    model="openai/gpt-oss-120b",
    temperature=0,
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)

gemini = gemini.bind_tools(tools)
groq = groq.bind_tools(tools)
nvidia = nvidia.bind_tools(tools)
#========================= get llm =========================

failed_providers = set()
def get_llm_response(messages):
    providers = [("groq",groq),("gemini",gemini),("nvidia",nvidia)]
    for provider_name,llm in providers:

        # Agar provider pehle hi fail ho chuka hai,
        # to is baar usko skip kar do
        if provider_name in failed_providers:
            print(f"Skipping {provider_name}")
            continue

        try:
            #print(f"Trying {provider_name}...")
            response=llm.invoke(messages)
            return response
        except Exception as e:
            print(f"{provider_name} failed: {e}")
            # Provider ko failed list mein remember kar lo
            failed_providers.add(provider_name)

    raise Exception("All LLM providers failed.")


#===================================================================================

class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage],add_messages]
    approval: str | None = None
    pending_tools: list[dict] = Field(default_factory=list)
    approved_tool: dict | None = None
    # CHANGE: human ka yes/no decision state mein store hoga.
    # Approval node decision dega aur after_approval() isi value
    # ko read karke tool ya agent par route karega.

def agent(state: AgentState):
    """LLM node that will answer"""

    system_message = SystemMessage(
        content="""
You are a coding agent.

When the user asks you to create, write, modify, or save code in a file,
you MUST use the appropriate file tool instead of only providing the code
in the chat.

Use:
- write_file → create a new file or overwrite a file
- edit_file → modify an existing file
- read_file → read an existing file
- list_files → list project files
- command_run → run terminal commands

For file creation requests, determine the appropriate filename and
content, then call the required tool.
"""
    )
    # CHANGE: LLM ko coding-agent ka clear instruction de rahe hain.
    # Pehle LLM user ke request ko sirf "code likhne" ka request samajh
    # kar code chat mein de raha tha.
    # Ab usse explicitly bataya hai ki file create/write karne ke liye
    # actual tool use karna mandatory hai.

    message = [system_message] + state.messages
    # CHANGE: SystemMessage ko conversation ke beginning mein add kiya.
    # Isse LLM ko har agent call par ye instruction milega.

    response = get_llm_response(message)

    return {
        "messages": [response]
    }

def classify_tools(state: AgentState):

    last_message = state.messages[-1]

    return {
        "pending_tools": last_message.tool_calls
    }

def should_continue(state: AgentState):

    if not state.pending_tools:
        return END

    dangerous_tools = {
        "write_file",
        "edit_file",
        "command_run"
    }

    next_tool = state.pending_tools[0]

    if next_tool["name"] in dangerous_tools:
        return "approval"

    return "process"

def human_approval(state: AgentState):

    tool_call = state.pending_tools[0]

    approval = interrupt(
        f"""
Approval required
Tool: {tool_call["name"]}

Arguments:
{tool_call["args"]}
"""
    )

    return {
        "approval": approval
    }

def process_approval(state: AgentState):

    tool_call = state.pending_tools[0]
    dangerous_tools = {
        "write_file",
        "edit_file",
        "command_run"
    }

    if tool_call["name"] not in dangerous_tools:
        return {
            "approved_tool": tool_call,
            "pending_tools": state.pending_tools[1:]
        }

    if state.approval == "yes":
        return {
            "approved_tool": tool_call,
            "pending_tools": state.pending_tools[1:],
            "approval": None
        }

    rejection_message = ToolMessage(
        content=(
            f"The user rejected the execution of "
            f"the tool '{tool_call['name']}'. "
            "Do not execute this tool call."
        ),
        tool_call_id=tool_call["id"]
    )

    return {
        "approved_tool": None,
        "pending_tools": state.pending_tools[1:],
        "approval": None,
        "messages": [rejection_message]
    }

def after_process(state: AgentState):

    if state.approved_tool:
        return "execute"

    if state.pending_tools:
        return "approval"

    return "agent"

def execute_approved_tool(state: AgentState):

    tool_call = state.approved_tool

    message = AIMessage(
        content="",
        tool_calls=[tool_call]
    )

    return {
        "messages": [message],
        "approved_tool": None
    }

def handle_tool_error(error: Exception) -> str:
    return f"Tool failed: {str(error)}"


tool_node = ToolNode([
    list_files,
    read_file,
    write_file,
    edit_file,
    command_run
    ],
    handle_tool_errors=handle_tool_error
)

# ============================================================
# 7. GRAPH
# ============================================================
conn = sqlite3.connect(
    "checkpoints.db",
    check_same_thread=False
)
checkpointer = SqliteSaver(conn)
graph = StateGraph(AgentState)

# Nodes
graph.add_node("agent", agent)
graph.add_node("tool", tool_node)
graph.add_node("approval", human_approval)
graph.add_node("classify_tools", classify_tools)
graph.add_node("process_approval", process_approval)
graph.add_node("execute_approved_tool", execute_approved_tool)

# START → AGENT
graph.add_edge(START, "agent")
# AGENT ke baad tools ko process karenge
graph.add_edge("agent", "classify_tools")
graph.add_conditional_edges(
    "classify_tools",
    should_continue,
    {
        "approval": "approval",
        "process": "process_approval",
        END: END
    }
)

# APPROVAL → PROCESS
graph.add_edge("approval", "process_approval")

graph.add_conditional_edges(
    "process_approval",
    after_process,
    {
        "execute": "execute_approved_tool",
        "approval": "approval",
        "agent": "agent"
    }
)

graph.add_edge("execute_approved_tool", "tool")

# TOOL → AGENT
graph.add_edge("tool", "agent")

app = graph.compile(checkpointer=checkpointer)
# ==========================================================================
thread_id = str(uuid.uuid4())

config = {
    "configurable": {
        "thread_id": thread_id
    }
}

# ==========================================================================
while True:

    user_input = input("You: ")

    if user_input.lower() in ["bye","exit","quit"]:
        break

    if user_input.lower() == "/new":
        thread_id = str(uuid.uuid4())
        config = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        # CHANGE:
        # Sirf thread_id change karna enough nahi hai.
        # config mein bhi new thread_id dena zaroori hai,
        # warna checkpointing purane thread mein hi continue hogi.
        print("Started a new conversation.")
        continue

    # Har new user request ke liye providers ko fresh try karenge
    failed_providers.clear()

    input_data = {
        "messages": [
            HumanMessage(content=user_input)
        ],
        "approval": None,
        "pending_tools": [],
        "approved_tool": None
    }

    # CHANGE:
    # Har new user request par approval ko None kar rahe hain.
    # Previous request ka yes/no next request mein reuse nahi hoga.

    while True:

        interrupted = False

        for chunk in app.stream(
            input_data,
            config=config,
            stream_mode=["messages","updates"]
        ):

            mode, data = chunk

            # =========================
            # AI MESSAGE STREAM
            # =========================
            if mode == "messages":

                message_chunk, metadata = data

                if isinstance(message_chunk, ToolMessage):
                    continue

                if isinstance(message_chunk, AIMessage):
                    if message_chunk.content:
                        print(
                            message_chunk.content,
                            end="",
                            flush=True
                        )

            # =========================
            # GRAPH UPDATES
            # =========================

            elif mode == "updates":

                update = data

                if "execute_approved_tool" in update:

                    tool_data = update[
                        "execute_approved_tool"
                    ]

                    message = tool_data[
                        "messages"
                    ][0]

                    if isinstance(message, AIMessage):

                        if message.tool_calls:

                            for tool_call in message.tool_calls:

                                print(
                                    f"\n🔧 Using tool: {tool_call['name']}"
                                )

                # HITL INTERRUPT
                if "__interrupt__" in update:

                    interrupted = True

                    interrupt_data = update[
                        "__interrupt__"
                    ][0]

                    print(
                        interrupt_data.value
                    )

        print()

        # =========================
        # RESUME AFTER APPROVAL
        # =========================

        if interrupted:

            while True:

                approval = input("Approve? (yes/no): ").strip().lower()

                if approval in ["yes","no"]:
                    break

                print("Please type yes or no.")

            # CHANGE:
            # Invalid input handle kiya.
            # Sirf yes/no par hi paused graph resume hoga.

            input_data = Command(
                resume=approval
            )

            # CHANGE:
            # interrupt() se paused graph ko resume kar rahe hain.
            # approval value human_approval() ke interrupt()
            # ke return value ke roop mein receive hogi.

            continue

        break