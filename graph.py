from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from langchain_core.messages import HumanMessage,BaseMessage
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from pathlib import Path
import subprocess
from typing import Annotated
from langgraph.graph.message import add_messages

@tool
def list_files() -> list[str]:
    """List all files and folders in the current project directory."""
    files = []
    for path in Path(".").iterdir():
        if path.name in [".cenv", "__pycache__", ".git", ".env"]:
            continue
        files.append(path.name)
    return files


@tool
def read_file(file_path: str) -> str:
    """Read the complete contents of a file."""
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} is not a file."
    return path.read_text()


@tool
def write_file(file_path: str, content: str) -> str:
    """Create or overwrite a file with the provided content."""
    with open(file_path, "w") as file:
        file.write(content)
    return f"{file_path} created successfully."


@tool
def edit_file(file_path: str,old_text: str,new_text: str) -> str:
    """Replace specific existing text in a file with new text."""
    path = Path(file_path)
    if not path.is_file():
        return f"{file_path} not in project."
    content = path.read_text()
    if old_text not in content:
        return f"Text not found in {file_path}."
    content = content.replace(old_text, new_text, 1)
    path.write_text(content)
    return f"{file_path} updated successfully."


@tool
def command_run(command: str) -> str:
    """Run a terminal command in the current project directory."""

    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout + result.stderr

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

# LLM ko bataya ki list_files naam ka tool available hai
llm = llm.bind_tools([list_files,read_file,write_file,edit_file,command_run])

class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage], add_messages]


def agent(state):
    print("Agent node running...")
    response = llm.invoke(state.messages)
    return {
        "messages": [response]
    }


# Ye tool calls ko actually execute karega
tool_node = ToolNode([ list_files,
    read_file,
    write_file,
    edit_file,
    command_run])


# Decide karega: tool chalana hai ya graph khatam karna hai
def should_continue(state):
    last_message = state.messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


graph = StateGraph(AgentState)
graph.add_node("agent", agent)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent",
    should_continue
)

graph.add_edge("tools", "agent")
app = graph.compile()

while True:

    user_input = input("You: ")
    if user_input.lower() == "exit":
        break
    result = app.invoke({
        "messages": [
            HumanMessage(content=user_input)
        ]
    })

    print("AI:", result["messages"][-1].content)