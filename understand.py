# ============================================================
# IMPORTS
# ============================================================

import uuid
# uuid ka use unique thread_id banane ke liye hota hai.
# Har new conversation ko ek unique ID milegi.

import asyncio
# asyncio ka use asynchronous functions ko run karne ke liye hota hai.
# MCP ke saath async communication ke liye iska use ho raha hai.

import sqlite3
# SQLite database ke saath connection banane ke liye.

import os
# Environment variables jaise API keys read karne ke liye.


from typing import Annotated, Any
# Annotated -> kisi type ke saath extra information attach karne ke liye.
# Any -> jab exact type pata na ho ya koi bhi type allowed ho.


from pydantic import BaseModel, Field, create_model
# BaseModel -> AgentState jaisi Pydantic class banane ke liye.
# Field -> fields ke default values/metadata define karne ke liye.
# create_model -> runtime par dynamically Pydantic model banane ke liye.


from langchain_google_genai import ChatGoogleGenerativeAI
# Google Gemini LLM ko LangChain ke through use karne ke liye.


from langchain_groq import ChatGroq
# Groq ke LLM models ko LangChain ke through use karne ke liye.


from langchain_openai import ChatOpenAI
# OpenAI-compatible APIs ko LangChain ke through use karne ke liye.
# Yahan NVIDIA API ko OpenAI-compatible interface se use kiya ja raha hai.


from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage
)
# BaseMessage -> LangChain ke messages ka base type.
# HumanMessage -> user ka message.
# AIMessage -> AI/LLM ka message.
# ToolMessage -> tool execution ka result.
# SystemMessage -> AI ko system-level instructions dene ke liye.


from langchain_core.tools import StructuredTool
# StructuredTool ka use MCP tools ko LangChain tools mein convert karne ke liye.


from langgraph.graph import StateGraph, START, END
# StateGraph -> LangGraph ka graph banane ke liye.
# START -> graph ka starting point.
# END -> graph ka ending point.


from langgraph.graph.message import add_messages
# add_messages LangGraph state ke messages ko properly merge/append karta hai.
# Isko Annotated ke saath use karenge.


from langgraph.prebuilt import ToolNode
# ToolNode LangChain tools ko execute karne ke liye ready-made LangGraph node hai.


from langgraph.checkpoint.sqlite import SqliteSaver
# SqliteSaver graph ki state ko SQLite database mein save karta hai.
# Isse conversation/checkpoint persist ho sakta hai.


from langgraph.types import interrupt, Command
# interrupt -> human approval ke liye graph ko pause karta hai.
# Command -> interrupt ke baad graph ko resume karne ke liye.


from mcp import Client, StdioServerParameters
# Client -> MCP server se connect karne ke liye.
# StdioServerParameters -> MCP server ko command ke through start karne ke liye.


# ============================================================
# MCP
# ============================================================

# MCP server ko start karne ki configuration.
mcp_server = StdioServerParameters(
    command="python",
    # MCP server Python se run hoga.

    args=["mcp_server.py"]
    # Python ko mcp_server.py file run karne ke liye bola ja raha hai.
)


# Ye special marker MCP server se error ka type identify karne ke liye use hoga.
MCP_ERROR_PREFIX = "__MCP_ERROR_TYPE__:"


# ============================================================
# MCP RESULT EXTRACTION
# ============================================================

# MCP result ko easily usable Python value mein convert karta hai.
def extract_mcp_result(result):

    # Pehle structured_content try kar rahe hain.
    data = getattr(result, "structured_content", None)

    # Agar structured content dictionary hai aur usme "result" key hai,
    # to actual result ko extract kar lo.
    if isinstance(data, dict) and "result" in data:
        data = data["result"]

    # Agar structured data mil gaya to wahi return kar do.
    if data is not None:
        return data

    # Agar structured content nahi mila,
    # to normal content check karenge.
    content = getattr(result, "content", None) or []

    # Text content store karne ke liye empty list.
    texts = []

    # MCP content ke har item ko check karo.
    for item in content:

        # Agar item ke paas text attribute hai,
        # to us text ko list mein add karo.
        if hasattr(item, "text"):
            texts.append(item.text)

    # Agar text mila hai to sab text ko newline ke saath join kar do.
    if texts:
        return "\n".join(texts)

    # Kuch bhi result nahi mila.
    return None


# ============================================================
# MCP RESULT PROCESSING
# ============================================================

# MCP tool ke result ko process karke simple output/error return karta hai.
def process_mcp_result(result):

    # MCP result se actual data nikaalo.
    data = extract_mcp_result(result)

    # Agar result hi nahi mila to generic error return karo.
    if data is None:
        return "Tool failed: Exception: MCP tool returned no result."

    # Agar data string hai aur hamara custom error marker hai,
    # to original error type aur message extract karo.
    if isinstance(data, str) and MCP_ERROR_PREFIX in data:

        # Marker ke baad wala part nikalo.
        error_data = data.split(MCP_ERROR_PREFIX, 1)[1]

        # Error name aur error message ko separate karo.
        error_name, error_message = error_data.split(":", 1)

        # Standard format mein error return karo.
        return f"Tool failed: {error_name}: {error_message}"

    # Agar MCP SDK ne result ko error mark kiya hai,
    # to tool failure return karo.
    if result.is_error:
        return f"Tool failed: Exception: {data}"

    # Agar koi error nahi hai to actual data return karo.
    return data


# ============================================================
# MCP TOOL CALL - ASYNC
# ============================================================

# MCP tool ko asynchronously call karta hai.
async def mcp_call_tool(tool_name, arguments):

    # MCP server ke saath temporary client connection banao.
    async with Client(mcp_server) as client:

        # MCP server ke specified tool ko call karo.
        result = await client.call_tool(
            tool_name,
            arguments
        )

        # Tool ke result ko process karke return karo.
        return process_mcp_result(result)


# ============================================================
# MCP TOOL CALL - SYNC WRAPPER
# ============================================================

# Normal synchronous Python code se async MCP function call karne ke liye.
def call_mcp_tool(tool_name, arguments):

    # asyncio.run async function ko execute karta hai.
    return asyncio.run(
        mcp_call_tool(tool_name, arguments)
    )


# ============================================================
# MCP DISCOVERY
# ============================================================

# MCP server par available saare tools discover karta hai.
async def discover_mcp_tools():

    # Discovered tools yahan store honge.
    discovered_tools = []

    # Pagination ke liye initially cursor None hai.
    cursor = None

    # MCP server se connection banao.
    async with Client(mcp_server) as client:

        # Jab tak saare pages nahi mil jaate tab tak loop chalega.
        while True:

            # MCP server se tools ka current page fetch karo.
            page = await client.list_tools(cursor=cursor)

            # Current page ke tools ko list mein add karo.
            discovered_tools.extend(page.tools)

            # Agar next page nahi hai to loop stop.
            if page.next_cursor is None:
                break

            # Next request ke liye next cursor save karo.
            cursor = page.next_cursor

    # Saare discovered tools return karo.
    return discovered_tools


# ============================================================
# SCHEMA
# ============================================================

# MCP ka JSON schema -> Python/Pydantic type mein convert karta hai.
def schema_type(schema, name):

    # Agar schema dictionary nahi hai,
    # to exact type pata nahi hai, isliye Any return karo.
    if not isinstance(schema, dict):
        return Any

    # Agar enum hai to currently string type treat kar rahe hain.
    if "enum" in schema:
        return str

    # anyOf/oneOf complex schemas ko generic Any treat kar rahe hain.
    if "anyOf" in schema or "oneOf" in schema:
        return Any

    # Schema ke "type" ko nikalo.
    schema_kind = schema.get("type")

    # JSON string -> Python str.
    if schema_kind == "string":
        return str

    # JSON integer -> Python int.
    if schema_kind == "integer":
        return int

    # JSON number -> Python float.
    if schema_kind == "number":
        return float

    # JSON boolean -> Python bool.
    if schema_kind == "boolean":
        return bool

    # JSON array -> Python list.
    if schema_kind == "array":

        # Array ke andar kis type ka data hai,
        # uska schema recursively process karo.
        item_type = schema_type(
            schema.get("items", {}),
            f"{name}Item"
        )

        # Example:
        # string array -> list[str]
        # integer array -> list[int]
        return list[item_type]

    # JSON object -> nested Pydantic model.
    if schema_kind == "object":

        # Object ke fields/properties nikaalo.
        properties = schema.get("properties", {})

        # Required fields ki list ko set bana do.
        required = set(schema.get("required", []))

        # Dynamically Pydantic fields store karne ke liye dictionary.
        fields = {}

        # Har property ko process karo.
        for field_name, field_schema in properties.items():

            # Property ka Python type recursively determine karo.
            field_type = schema_type(
                field_schema,
                f"{name}_{field_name}"
            )

            # Field ka description agar available hai to nikalo.
            description = field_schema.get("description")

            # Agar field required hai.
            if field_name in required:

                # Description hai to Field(...) use karo.
                # ... ka matlab field required hai.
                default = (
                    Field(..., description=description)
                    if description
                    else ...
                )

                # Field ka type aur default Pydantic model ke liye store karo.
                fields[field_name] = (field_type, default)

            # Agar field optional hai.
            else:

                # Description hai to None ke saath Field banao.
                default = (
                    Field(None, description=description)
                    if description
                    else None
                )

                # Optional field ko type | None bana rahe hain.
                fields[field_name] = (
                    field_type | None,
                    default
                )

        # Runtime par Pydantic model create karo.
        return create_model(name, **fields)

    # Agar schema ka type unknown hai to Any.
    return Any


# ============================================================
# MCP ARGUMENT SCHEMA
# ============================================================

# MCP tool ke input schema ko complete Pydantic object schema mein convert karta hai.
def create_mcp_args_schema(tool_name, input_schema):

    # Agar input_schema dictionary nahi hai to empty dictionary use karo.
    if not isinstance(input_schema, dict):
        input_schema = {}

    # Tool ke input schema ko object schema mein convert karo.
    return schema_type(
        {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", [])
        },
        f"{tool_name.replace('-', '_')}Input"
    )


# ============================================================
# DYNAMIC TOOLS
# ============================================================

# Ek discovered MCP tool ko LangChain StructuredTool mein convert karta hai.
def create_mcp_tool(mcp_tool):

    # MCP tool ka original name.
    mcp_name = mcp_tool.name

    # LangChain tool ke liye naam banate hain.
    # Example:
    # read_file -> mcp_read_file
    langchain_name = f"mcp_{mcp_name}"

    # MCP tool ka description.
    # Agar description nahi hai to fallback description use hoga.
    description = (
        mcp_tool.description
        or f"MCP tool: {mcp_name}"
    )

    # MCP tool ka input schema retrieve karo.
    input_schema = getattr(
        mcp_tool,
        "inputSchema",
        None
    )

    # Agar inputSchema nahi mila to alternative input_schema attribute try karo.
    if input_schema is None:
        input_schema = getattr(
            mcp_tool,
            "input_schema",
            {}
        )

    # MCP JSON schema ko Pydantic args schema mein convert karo.
    args_schema = create_mcp_args_schema(
        mcp_name,
        input_schema
    )

    # Ye actual function hai jo LangChain tool call hone par execute hoga.
    def run_mcp_tool(**kwargs):

        # MCP server par actual tool call karo.
        return call_mcp_tool(
            mcp_name,
            kwargs
        )

    # Function ka name dynamically set karo.
    run_mcp_tool.__name__ = langchain_name

    # Function ki documentation/description set karo.
    run_mcp_tool.__doc__ = description

    # Normal Python function ko LangChain StructuredTool mein convert karo.
    return StructuredTool.from_function(
        func=run_mcp_tool,
        name=langchain_name,
        description=description,
        args_schema=args_schema
    )


# ============================================================
# DISCOVER MCP TOOLS
# ============================================================

# MCP server se dynamically saare tools discover karo.
mcp_tool_definitions = asyncio.run(
    discover_mcp_tools()
)


# Har MCP tool ko LangChain StructuredTool mein convert karo.
tools = [
    create_mcp_tool(mcp_tool)
    for mcp_tool in mcp_tool_definitions
]


# Discovered tools ko terminal par print karo.
print("\nMCP tools discovered:")


# Har discovered MCP tool ka naam print karo.
for mcp_tool in mcp_tool_definitions:

    # LangChain-style naam print hoga.
    print(f"- mcp_{mcp_tool.name}")


# Extra blank line for clean terminal output.
print()


# ============================================================
# DANGEROUS TOOLS
# ============================================================

# In tools ko execute karne se pehle human approval required hoga.
dangerous_tools = {
    "mcp_write_file",
    "mcp_edit_file",
    "mcp_command_run"
}


# ============================================================
# LLM
# ============================================================

# Gemini LLM initialize karo.
gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    # Gemini ka model select kiya.

    temperature=0
    # 0 ka matlab response ko relatively deterministic rakhna.
)


# Groq LLM initialize karo.
groq = ChatGroq(
    model="openai/gpt-oss-120b",
    # Groq par available model.

    temperature=0
    # Deterministic behavior ke liye temperature 0.
)


# NVIDIA ka OpenAI-compatible API initialize karo.
nvidia = ChatOpenAI(
    model="openai/gpt-oss-120b",
    # NVIDIA endpoint par requested model.

    temperature=0,

    base_url="https://integrate.api.nvidia.com/v1",
    # OpenAI-compatible NVIDIA API ka base URL.

    api_key=os.getenv("NVIDIA_API_KEY")
    # API key environment variable se read hoti hai.
)


# ============================================================
# BIND TOOLS TO LLMs
# ============================================================

# Gemini ko available tools ke baare mein bata rahe hain.
gemini = gemini.bind_tools(tools)

# Groq ko bhi same tools provide karo.
groq = groq.bind_tools(tools)

# NVIDIA model ko bhi tools provide karo.
nvidia = nvidia.bind_tools(tools)


# ============================================================
# FAILED PROVIDERS
# ============================================================

# Jo LLM provider fail ho chuka hai usko temporarily skip karenge.
failed_providers = set()


# ============================================================
# LLM RESPONSE WITH FALLBACK
# ============================================================

# LLM providers ko ek ke baad ek try karta hai.
def get_llm_response(messages):

    # Provider priority/order.
    providers = [
        ("groq", groq),
        ("gemini", gemini),
        ("nvidia", nvidia)
    ]

    # Har provider ko try karo.
    for provider_name, llm in providers:

        # Agar provider pehle fail ho chuka hai,
        # to dobara try mat karo.
        if provider_name in failed_providers:

            # Terminal par inform karo.
            print(f"Skipping {provider_name}")

            # Next provider par jao.
            continue

        try:

            # Current LLM ko messages send karo.
            return llm.invoke(messages)

        except Exception as e:

            # Agar provider fail hua to error print karo.
            print(f"{provider_name} failed: {e}")

            # Provider ko failed set mein add karo.
            failed_providers.add(provider_name)

    # Agar teeno providers fail ho gaye.
    raise Exception("All LLM providers failed.")


# ============================================================
# STATE
# ============================================================

# Agent ki complete state define kar rahe hain.
class AgentState(BaseModel):

    # Conversation ke saare messages.
    #
    # Annotated ka second part add_messages hai.
    # Iska matlab new messages ko existing messages ke saath
    # intelligently merge/add kiya jayega.
    messages: Annotated[
        list[BaseMessage],
        add_messages
    ]

    # Human approval ka answer.
    # None ka matlab abhi approval nahi mila.
    approval: str | None = None

    # LLM ne jo tools call karne ko bola hai,
    # wo yahan pending rahenge.
    pending_tools: list[dict] = Field(
        default_factory=list
    )

    # Human-approved tool yahan temporarily store hoga.
    approved_tool: dict | None = None

    # Jo tool fail hua uski information yahan save hogi.
    failed_tool_call: dict | None = None

    # Error ka category/type yahan store hoga.
    error_type: str | None = None

    # Retry kitni baar hua uska counter.
    retry_count: int = 0


# ============================================================
# AGENT
# ============================================================

# Ye main LLM/agent node hai.
def agent(state: AgentState):

    # System instruction create karo.
    system_message = SystemMessage(
        content="""

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

"""
    )

    # System message + previous conversation LLM ko bhej rahe hain.
    response = get_llm_response(
        [system_message] + state.messages
    )

    # LLM ka response messages mein add karo.
    return {
        "messages": [response]
    }


# ============================================================
# TOOL FLOW
# ============================================================

# LLM ke latest message se tool calls extract karta hai.
def classify_tools(state: AgentState):

    # Conversation ka last message lo.
    last_message = state.messages[-1]

    # Last AI message ke tool_calls ko pending tools mein store karo.
    return {
        "pending_tools": last_message.tool_calls
    }


# ============================================================
# DECIDE NEXT STEP
# ============================================================

# Decide karta hai ki tool execute karna hai,
# approval lena hai ya agent ko stop karna hai.
def should_continue(state: AgentState):

    # Agar koi tool call nahi hai to graph end.
    if not state.pending_tools:
        return END

    # Agar first pending tool dangerous hai,
    # to human approval required.
    if state.pending_tools[0]["name"] in dangerous_tools:
        return "approval"

    # Normal/safe tool ko process karo.
    return "process"


# ============================================================
# HUMAN APPROVAL
# ============================================================

# Dangerous tool ke liye human se approval leta hai.
def human_approval(state: AgentState):

    # First pending tool nikalo.
    tool_call = state.pending_tools[0]

    # Graph ko interrupt karke human approval maango.
    approval = interrupt(
        f"""
Approval required
Tool: {tool_call["name"]}

Arguments:
{tool_call["args"]}
"""
    )

    # Approval ko state mein save karo.
    return {
        "approval": approval
    }


# ============================================================
# PROCESS APPROVAL
# ============================================================

# Approval ko check karke decide karta hai tool execute hoga ya reject.
def process_approval(state: AgentState):

    # First pending tool lo.
    tool_call = state.pending_tools[0]

    # Agar tool dangerous list mein nahi hai,
    # to direct approved maan lo.
    if tool_call["name"] not in dangerous_tools:

        return {
            "approved_tool": tool_call,

            # Current tool ko pending list se remove kar do.
            "pending_tools": state.pending_tools[1:]
        }

    # Agar human ne "yes" bola hai.
    if state.approval == "yes":

        return {
            # Tool execution ke liye approved tool save karo.
            "approved_tool": tool_call,

            # Current tool ko pending list se remove karo.
            "pending_tools": state.pending_tools[1:],

            # Approval ko reset karo.
            "approval": None
        }

    # Agar user ne approval nahi diya,
    # to ToolMessage ke through model ko inform karo.
    rejection_message = ToolMessage(
        content=(
            f"The user rejected the execution of the tool "
            f"'{tool_call['name']}'. Do not execute this tool call."
        ),

        # ToolMessage ko original tool call ID se connect karo.
        tool_call_id=tool_call["id"]
    )

    # Rejected tool ko execute nahi karenge.
    return {
        "approved_tool": None,

        # Pending list se rejected tool remove karo.
        "pending_tools": state.pending_tools[1:],

        # Approval reset karo.
        "approval": None,

        # Rejection message conversation mein add karo.
        "messages": [rejection_message]
    }


# ============================================================
# AFTER PROCESSING APPROVAL
# ============================================================

# Approval process ke baad next graph node decide karta hai.
def after_process(state: AgentState):

    # Agar tool approve ho gaya hai,
    # to execute node par jao.
    if state.approved_tool:
        return "execute"

    # Agar aur pending tools bache hain.
    if state.pending_tools:

        # Agar next tool dangerous hai,
        # to approval dobara lena padega.
        if state.pending_tools[0]["name"] in dangerous_tools:
            return "approval"

        # Agar safe tool hai to process karo.
        return "process"

    # Agar koi pending tool nahi hai,
    # to wapas agent ke paas jao.
    return "agent"


# ============================================================
# EXECUTE APPROVED TOOL
# ============================================================

# Approved tool ko ToolNode ke format mein execute karwata hai.
def execute_approved_tool(state: AgentState):

    # Approved tool retrieve karo.
    tool_call = state.approved_tool

    # AIMessage mein tool call wrap kar rahe hain.
    return {
        "messages": [
            AIMessage(
                # Tool call ke liye content empty hai.
                content="",

                # Actual approved tool call.
                tool_calls=[tool_call]
            )
        ],

        # Execute karne ke baad approved tool ko clear kar do.
        "approved_tool": None
    }


# ============================================================
# ERROR / RETRY
# ============================================================

# Python exception ko graph ke decision categories mein convert karta hai.
def classify_error(error: Exception) -> str:

    # Timeout ya connection issue generally temporary ho sakta hai,
    # isliye retry karo.
    if isinstance(
        error,
        (TimeoutError, ConnectionError)
    ):
        return "retry"

    # File missing/permission/directory issue ko agent handle karega.
    if isinstance(
        error,
        (
            FileNotFoundError,
            PermissionError,
            IsADirectoryError
        )
    ):
        return "agent"

    # Baaki unknown errors ko stop category mein rakho.
    return "stop"


# ============================================================
# RETRY TOOL
# ============================================================

# Failed tool ko dobara execute karne ke liye tool call recreate karta hai.
def retry_tool(state: AgentState):

    return {
        "messages": [
            AIMessage(
                # Tool execution message mein content empty.
                content="",

                # Failed tool ko dobara call karo.
                tool_calls=[state.failed_tool_call]
            )
        ],

        # Failed tool ko retry ke baad clear karo.
        "failed_tool_call": None,

        # Error type ko clear karo.
        "error_type": None
    }


# ============================================================
# CHECK TOOL RESULT
# ============================================================

# Tool execute hone ke baad uska result check karta hai.
def check_tool_result(state: AgentState):

    # Latest message retrieve karo.
    last_message = state.messages[-1]

    # Sirf ToolMessage ko inspect karna hai.
    if isinstance(last_message, ToolMessage):

        # Tool result ko string mein convert karo.
        content = str(last_message.content)

        # Agar result hamare failure format se start ho raha hai.
        if content.startswith("Tool failed:"):

            # Error information split karo.
            parts = content.split(":", 2)

            # Error name extract karo.
            error_name = (
                parts[1].strip()
                if len(parts) > 1
                else "Exception"
            )

            # Initially failed tool call None hai.
            failed_tool_call = None

            # Latest se oldest messages ki taraf search karo.
            for message in reversed(state.messages):

                # AIMessage mein tool calls ho sakte hain.
                if isinstance(message, AIMessage):

                    # AI ke saare tool calls check karo.
                    for tool_call in message.tool_calls:

                        # Agar ToolMessage ki ID
                        # AIMessage ke tool call ID se match karti hai.
                        if tool_call["id"] == last_message.tool_call_id:

                            # Ye hi failed tool call hai.
                            failed_tool_call = tool_call

                            # Inner loop stop.
                            break

                # Agar failed tool mil gaya to outer loop bhi stop.
                if failed_tool_call:
                    break

            # String error names ko actual Python exception classes
            # ke saath map kar rahe hain.
            error_classes = {
                "TimeoutError": TimeoutError,
                "ConnectionError": ConnectionError,
                "FileNotFoundError": FileNotFoundError,
                "PermissionError": PermissionError,
                "IsADirectoryError": IsADirectoryError
            }

            # Error name ke basis par exception object banao.
            # Unknown error -> generic Exception.
            error = error_classes.get(
                error_name,
                Exception
            )()

            # Exception ko classify karo.
            decision = classify_error(error)

            # Agar retry karna hai.
            if decision == "retry":

                # Maximum 3 retries allow hain.
                if state.retry_count < 3:

                    return {
                        # Graph ko retry mode batao.
                        "error_type": "retry",

                        # Retry counter increase karo.
                        "retry_count": state.retry_count + 1,

                        # Failed tool save karo.
                        "failed_tool_call": failed_tool_call
                    }

                # 3 retries complete ho gaye.
                return {
                    "error_type": "stop"
                }

            # Agar retry nahi karna,
            # to classification state mein save karo.
            return {
                "error_type": decision
            }

    # Agar tool failure nahi mila,
    # to error state clear/reset rakho.
    return {
        "error_type": None,
        "retry_count": 0,
        "failed_tool_call": None
    }


# ============================================================
# AFTER TOOL RESULT
# ============================================================

# Tool result check hone ke baad next node decide karta hai.
def after_tool_result(state: AgentState):

    # Retry required hai to retry_tool node.
    if state.error_type == "retry":
        return "retry_tool"

    # Agent ko error explain/handle karna hai.
    if state.error_type == "agent":
        return "agent"

    # Success ya stop dono cases mein agent ko control do.
    if state.error_type in [None, "stop"]:
        return "agent"

    # Fallback.
    return END


# ============================================================
# TOOL ERROR HANDLER
# ============================================================

# ToolNode ke raw exception ko standard string format mein convert karta hai.
def handle_tool_error(error: Exception) -> str:

    # Exception ka class name aur message return karo.
    return (
        f"Tool failed: "
        f"{type(error).__name__}: "
        f"{str(error)}"
    )


# ============================================================
# GRAPH
# ============================================================

# ToolNode create karo.
# Ye dynamically discovered LangChain tools ko execute karega.
tool_node = ToolNode(
    tools,

    # Tool error ko hamare custom handler se process karo.
    handle_tool_errors=handle_tool_error
)


# ============================================================
# SQLITE CHECKPOINT DATABASE
# ============================================================

# SQLite database ke saath connection banao.
conn = sqlite3.connect(
    "checkpoints.db",

    # Async/thread based execution mein same connection allow karne ke liye.
    check_same_thread=False
)


# SQLite connection ko LangGraph checkpoint saver mein wrap karo.
memory = SqliteSaver(conn)


# ============================================================
# CREATE STATE GRAPH
# ============================================================

# AgentState ko graph ka state schema bana rahe hain.
graph = StateGraph(AgentState)


# ============================================================
# ADD NODES
# ============================================================

# LLM agent node.
graph.add_node("agent", agent)

# Actual tool execution node.
graph.add_node("tool", tool_node)

# Human approval node.
graph.add_node("approval", human_approval)

# LLM ke tool calls classify karne wala node.
graph.add_node("classify_tools", classify_tools)

# Approval process karne wala node.
graph.add_node("process_approval", process_approval)

# Approved tool ko execution ke liye prepare karne wala node.
graph.add_node(
    "execute_approved_tool",
    execute_approved_tool
)

# Tool result/error check karne wala node.
graph.add_node(
    "check_tool_result",
    check_tool_result
)

# Failed tool retry karne wala node.
graph.add_node(
    "retry_tool",
    retry_tool
)


# ============================================================
# BASIC EDGES
# ============================================================

# Graph START hote hi agent node chalega.
graph.add_edge(
    START,
    "agent"
)


# Agent ke baad tool calls classify honge.
graph.add_edge(
    "agent",
    "classify_tools"
)


# ============================================================
# CONDITIONAL EDGE: CLASSIFY TOOLS
# ============================================================

# classify_tools ke baad should_continue function decide karega
# graph ko kis node par jaana hai.
graph.add_conditional_edges(

    # Source node.
    "classify_tools",

    # Decision function.
    should_continue,

    # Decision -> next node mapping.
    {
        # Dangerous tool -> human approval.
        "approval": "approval",

        # Safe tool -> approval processing.
        "process": "process_approval",

        # No tool -> graph end.
        END: END
    }
)


# ============================================================
# APPROVAL FLOW
# ============================================================

# Human approval lene ke baad
# approval result process_approval ko jayega.
graph.add_edge(
    "approval",
    "process_approval"
)


# ============================================================
# CONDITIONAL EDGE: PROCESS APPROVAL
# ============================================================

# Approval processing ke result ke basis par next node.
graph.add_conditional_edges(

    # Source node.
    "process_approval",

    # Decision function.
    after_process,

    # Decision -> node mapping.
    {
        # Approved tool -> execute.
        "execute": "execute_approved_tool",

        # Next dangerous tool -> approval.
        "approval": "approval",

        # Next safe pending tool -> process.
        "process": "process_approval",

        # Agar current tool reject hua/no pending -> agent.
        "agent": "agent"
    }
)


# ============================================================
# TOOL EXECUTION FLOW
# ============================================================

# Approved tool ko ToolNode ke paas bhejo.
graph.add_edge(
    "execute_approved_tool",
    "tool"
)


# Tool execute hone ke baad result check karo.
graph.add_edge(
    "tool",
    "check_tool_result"
)


# ============================================================
# CONDITIONAL EDGE: TOOL RESULT
# ============================================================

# Tool result ke basis par decide karo:
# retry / agent / end.
graph.add_conditional_edges(

    # Source node.
    "check_tool_result",

    # Decision function.
    after_tool_result,

    # Decision -> next node.
    {
        # Retry required.
        "retry_tool": "retry_tool",

        # Agent ko result/error handle karne do.
        "agent": "agent",

        # End.
        END: END
    }
)


# ============================================================
# RETRY FLOW
# ============================================================

# Retry tool ke baad dobara classify_tools par jao.
# Isse retry kiya hua tool normal tool flow mein enter karega.
graph.add_edge(
    "retry_tool",
    "classify_tools"
)


# ============================================================
# COMPILE GRAPH
# ============================================================

# Graph ko executable application mein compile karo.
#
# checkpointer=memory ka matlab:
# graph ki state SQLite database mein checkpoint hogi.
app = graph.compile(
    checkpointer=memory
)


# ============================================================
# RUN
# ============================================================

# Current conversation ke liye unique thread ID banao.
thread_id = str(uuid.uuid4())


# LangGraph configuration.
config = {
    "configurable": {
        # Checkpointer isi ID se conversation state identify karega.
        "thread_id": thread_id
    }
}


# ============================================================
# MAIN CHAT LOOP
# ============================================================

# Jab tak user exit nahi karta tab tak chat chalegi.
while True:

    # User se input lo.
    user_input = input("You: ")

    # Agar user bye/exit/quit bole,
    # to program stop kar do.
    if user_input.lower() in [
        "bye",
        "exit",
        "quit"
    ]:
        break


    # ========================================================
    # NEW CONVERSATION
    # ========================================================

    # /new command se completely new conversation/thread create hoga.
    if user_input.lower() == "/new":

        # New unique thread ID.
        thread_id = str(uuid.uuid4())

        # New thread ke liye config update karo.
        config = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        # User ko confirmation.
        print("Started a new conversation.")

        # Main loop ke next iteration par jao.
        continue


    # ========================================================
    # RESET FAILED PROVIDERS
    # ========================================================

    # Har new user request par failed provider list clear karo.
    #
    # Example:
    # Agar previous request mein Groq fail hua tha,
    # next request mein Groq ko dobara try karenge.
    failed_providers.clear()


    # ========================================================
    # INPUT STATE
    # ========================================================

    # User input ko LangGraph state format mein convert karo.
    input_data = {

        # User ka message HumanMessage mein wrap karo.
        "messages": [
            HumanMessage(
                content=user_input
            )
        ],

        # Approval state fresh request ke liye None.
        "approval": None,

        # Initially koi pending tool nahi.
        "pending_tools": [],

        # Initially koi approved tool nahi.
        "approved_tool": None,

        # Initially koi failed tool nahi.
        "failed_tool_call": None,

        # Initially error type None.
        "error_type": None,

        # Retry counter 0 se start.
        "retry_count": 0
    }


    # ========================================================
    # INNER GRAPH LOOP
    # ========================================================

    # Approval interrupt hone par isi loop se resume karenge.
    while True:

        # Initially interrupt nahi hua.
        interrupted = False


        # ====================================================
        # STREAM GRAPH EXECUTION
        # ====================================================

        # Graph ko stream mode mein run karo.
        for chunk in app.stream(

            # Graph ko input state.
            input_data,

            # Current conversation ka thread/checkpoint config.
            config=config,

            # Do types ke events chahiye:
            # messages -> streaming LLM messages
            # updates -> graph state/node updates
            stream_mode=["messages", "updates"]
        ):

            # Chunk ko mode aur data mein unpack karo.
            mode, data = chunk


            # =================================================
            # MESSAGE STREAM
            # =================================================

            if mode == "messages":

                # Message chunk aur metadata separate karo.
                message_chunk, metadata = data


                # ToolMessage ko direct print nahi karna.
                if isinstance(
                    message_chunk,
                    ToolMessage
                ):
                    continue


                # Agar AI ka message chunk hai.
                if isinstance(
                    message_chunk,
                    AIMessage
                ):

                    # Agar AI ke paas actual text content hai.
                    if message_chunk.content:

                        # Text ko terminal par print karo.
                        print(
                            message_chunk.content,

                            # Newline immediately nahi.
                            end="",

                            # Output immediately terminal par show karo.
                            flush=True
                        )


            # =================================================
            # GRAPH UPDATES
            # =================================================

            elif mode == "updates":

                # Current graph update ko store karo.
                update = data


                # Agar approved tool execution node update hua.
                if "execute_approved_tool" in update:

                    # Node ka data retrieve karo.
                    tool_data = update[
                        "execute_approved_tool"
                    ]

                    # Us node ka first message retrieve karo.
                    message = tool_data["messages"][0]


                    # Agar message AIMessage hai.
                    if isinstance(
                        message,
                        AIMessage
                    ):

                        # AIMessage ke tool calls loop karo.
                        for tool_call in message.tool_calls:

                            # User ko terminal mein batao
                            # ki kaunsa tool use ho raha hai.
                            print(
                                f"\n🔧 Using tool: "
                                f"{tool_call['name']}"
                            )


                # =================================================
                # INTERRUPT CHECK
                # =================================================

                # Agar LangGraph ne interrupt generate kiya.
                if "__interrupt__" in update:

                    # Interrupted flag true.
                    interrupted = True

                    # First interrupt object retrieve karo.
                    interrupt_data = update[
                        "__interrupt__"
                    ][0]

                    # Human approval message print karo.
                    print(
                        interrupt_data.value
                    )


        # Streaming complete hone ke baad newline.
        print()


        # =====================================================
        # RESUME AFTER HUMAN APPROVAL
        # =====================================================

        # Agar graph interrupt hua tha.
        if interrupted:

            # Jab tak valid yes/no answer nahi milta.
            while True:

                # User se approval input lo.
                approval = input(
                    "Approve? (yes/no): "
                ).strip().lower()


                # Sirf yes/no accept karo.
                if approval in [
                    "yes",
                    "no"
                ]:
                    break


                # Invalid input par user ko dobara bolo.
                print(
                    "Please type yes or no."
                )


            # Interrupt ko human ke answer ke saath resume karo.
            input_data = Command(
                resume=approval
            )

            # Inner loop continue karo,
            # graph wahi se resume hoga jahan interrupt hua tha.
            continue


        # Agar interrupt nahi hua,
        # to current graph execution complete hai.
        break