import uuid
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage,HumanMessage,AIMessage, ToolMessage
from pathlib import Path
from langgraph.graph import StateGraph,START,END
from typing import Annotated
from pydantic import BaseModel
import subprocess
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
import os

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

@tool
def test_error() -> str:
    """Test tool error handling."""
    raise ValueError("Something went wrong inside the tool")
#===========================tools======================================
tools =[
    list_files,
    read_file,
    write_file,
    edit_file,
    command_run,
    test_error
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



class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage],add_messages]

def agent(state: AgentState):
    """LLM node that will answer"""
    message = state.messages
    response = get_llm_response(message)
    return {
        "messages": [response]
    }

def should_continue(state: AgentState):
    last_message= state.messages[-1]
    if last_message.tool_calls:
        return "tool"
    return END

def handle_tool_error(error: Exception) -> str:
    return f"❌ Tool failed: {str(error)}"


tool_node = ToolNode([
    list_files,
    read_file,
    write_file,
    edit_file,
    command_run,
    test_error
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

# START → AGENT
graph.add_edge(START, "agent")
# AGENT ke baad decision
graph.add_conditional_edges("agent",should_continue)
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

    # Har new user request ke liye providers ko fresh try karenge
    failed_providers.clear()

    for chunk in app.stream(
        {
            "messages": [
                HumanMessage(content=user_input)
            ]
        },
        config=config,
        stream_mode=["messages", "updates"]
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
                    print(message_chunk.content, end="", flush=True)

        # =========================
        # GRAPH UPDATES
        # =========================
        elif mode == "updates":

            update = data

            # Agent ne tool call kiya
            if "agent" in update:

                message = update["agent"]["messages"][-1]

                if isinstance(message, AIMessage):

                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            print(
                                f"\n🔧 Using tool: {tool_call['name']}")
    print()