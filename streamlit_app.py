import subprocess
from pathlib import Path
import time
import requests
import streamlit as st

st.set_page_config(
    page_title="Coding Agent",
    page_icon="🤖",
    layout="wide"
)


DEFAULT_API_URL="http://127.0.0.1:8000"


if "api_url" not in st.session_state:
    st.session_state.api_url=DEFAULT_API_URL

if "token" not in st.session_state:
    st.session_state.token=None

if "user" not in st.session_state:
    st.session_state.user=None

if "thread_id" not in st.session_state:
    st.session_state.thread_id=None

if "messages" not in st.session_state:
    st.session_state.messages=[]

if "workspace_path" not in st.session_state:
    st.session_state.workspace_path=None

if "pending_approval" not in st.session_state:
    st.session_state.pending_approval=False

if "approval_request" not in st.session_state:
    st.session_state.approval_request=None

if "latest_progress" not in st.session_state:
    st.session_state.latest_progress={}
    st.session_state.latest_changes=[]

if "latest_changes" not in st.session_state:
    st.session_state.latest_changes=[]

if "chat_history" not in st.session_state:
    st.session_state.chat_history=[]

if "chat_history_loaded" not in st.session_state:
    st.session_state.chat_history_loaded=False


def api_request(method,path,payload=None):

    headers={}

    if st.session_state.token:
        headers["Authorization"]=f"Bearer {st.session_state.token}"

    response=requests.request(
        method,
        f"{st.session_state.api_url.rstrip('/')}{path}",
        json=payload,
        headers=headers,
        timeout=30
    )

    try:
        data=response.json()
    except Exception:
        data={"detail":response.text}

    if response.status_code>=400:
        raise RuntimeError(
            data.get("detail","Request failed")
        )

    return data


def login(email,password):

    result=api_request(
        "POST",
        "/auth/login",
        {
            "email":email,
            "password":password
        }
    )

    st.session_state.token=result["access_token"]

    st.session_state.user=api_request(
        "GET",
        "/auth/me"
    )

    workspace=api_request(
        "GET",
        "/workspace"
    )

    st.session_state.workspace_path=workspace.get(
        "workspace_path"
    )

    load_chat_history()


def register(email,password):

    return api_request(
        "POST",
        "/auth/register",
        {
            "email":email,
            "password":password
        }
    )


def verify_otp(email,otp):

    return api_request(
        "POST",
        "/auth/verify-otp",
        {
            "email":email,
            "otp":otp
        }
    )


def choose_folder():

    script=(
        'POSIX path of '
        '(choose folder with prompt '
        '"Select your coding project folder")'
    )

    result=subprocess.run(
        ["osascript","-e",script],
        capture_output=True,
        text=True
    )

    if result.returncode!=0:
        return None

    return result.stdout.strip().rstrip("/")


def load_chat_history():

    result=api_request(
        "GET",
        "/agent/chats"
    )

    st.session_state.chat_history=result.get(
        "chats",
        []
    )

    st.session_state.chat_history_loaded=True


def open_chat(thread_id):

    result=api_request(
        "GET",
        f"/agent/chats/{thread_id}"
    )

    st.session_state.thread_id=result["thread_id"]
    st.session_state.messages=result.get(
        "messages",
        []
    )

    st.session_state.pending_approval=False
    st.session_state.approval_request=None
    st.session_state.latest_progress={}
    st.session_state.latest_changes=[]

    st.rerun()


def select_workspace():

    folder=choose_folder()

    if not folder:
        return

    result=api_request(
        "POST",
        "/workspace/select",
        {
            "folder_path":folder
        }
    )

    st.session_state.workspace_path=result[
        "workspace_path"
    ]

    st.session_state.messages=[]
    st.session_state.thread_id=None
    st.session_state.pending_approval=False
    st.session_state.approval_request=None
    st.session_state.latest_progress={}
    st.session_state.latest_changes=[]

    st.success(
        "Workspace selected successfully."
    )

    st.rerun()


def refresh_workspace():

    result=api_request(
        "GET",
        "/workspace"
    )

    st.session_state.workspace_path=result.get(
        "workspace_path"
    )


def render_progress(progress):

    st.markdown("### Agent Progress")

    plan=progress.get("plan")

    if plan:
        st.markdown("**Plan**")

        for index,step in enumerate(
            plan,
            start=1
        ):
            st.write(f"{index}. {step}")

    events=progress.get("events",[])

    if events:
        st.markdown("**Activity**")

        for index,event in enumerate(events,1):

            message=event.get("message","Working...")
            tool=event.get("tool")

            if tool:
                st.write(
                    f"{index}. {message} — `{tool}`"
                )
            else:
                st.write(
                    f"{index}. {message}"
                )

            args=event.get("args") or {}

            if tool=="mcp_write_file" and args:
                with st.expander(
                    f"View code to write — {args.get('file_path','file')}",
                    expanded=False
                ):
                    st.caption(
                        f"Path: {args.get('file_path','')}"
                    )
                    st.code(
                        args.get("content",""),
                        language="python"
                    )

            elif tool=="mcp_edit_file" and args:
                with st.expander(
                    f"View edit — {args.get('file_path','file')}",
                    expanded=False
                ):
                    st.caption(
                        f"Path: {args.get('file_path','')}"
                    )
                    st.markdown("**Old code**")
                    st.code(
                        args.get("old_text",""),
                        language="python"
                    )
                    st.markdown("**New code**")
                    st.code(
                        args.get("new_text",""),
                        language="python"
                    )

            elif tool=="mcp_command_run" and args:
                with st.expander(
                    "View command",
                    expanded=False
                ):
                    st.code(
                        args.get("command",""),
                        language="bash"
                    )

    elif progress.get("message"):
        st.info(progress["message"])

    if progress.get("approval_request"):
        st.warning(
            progress["approval_request"]
        )

    if progress.get("error"):
        st.error(progress["error"])


def render_changes(changes):

    if not changes:
        return

    st.markdown("### Files Changed")

    for change in changes:

        operation=change.get("operation","changed")
        path=change.get("path","")

        if operation=="created":
            st.success(f"Created: `{path}`")

            with st.expander(
                "View complete file",
                expanded=True
            ):
                st.code(
                    change.get("content",""),
                    language=Path(path).suffix.lstrip(".") or "text"
                )

        elif operation=="modified":
            st.info(f"Modified: `{path}`")

            with st.expander(
                "View diff",
                expanded=True
            ):
                st.code(
                    change.get("diff",""),
                    language="diff"
                )

            with st.expander(
                "View current file",
                expanded=False
            ):
                st.code(
                    change.get("content",""),
                    language=Path(path).suffix.lstrip(".") or "text"
                )

        elif operation=="deleted":
            st.error(f"Deleted: `{path}`")

            with st.expander(
                "View deleted content",
                expanded=False
            ):
                st.code(
                    change.get("content",""),
                    language=Path(path).suffix.lstrip(".") or "text"
                )


def wait_for_task(task_id):

    progress_box=st.empty()

    for _ in range(180):

        result=api_request(
            "GET",
            f"/agent/task/{task_id}"
        )

        status=result["status"]
        progress=result.get("progress") or {}

        st.session_state.latest_progress=progress

        with progress_box.container():
            render_progress(progress)

        if status in ["completed","awaiting_approval"]:
            task_result=result["result"] or {}
            st.session_state.latest_changes=task_result.get("changes",[])
            return task_result

        if status=="failed":

            data=result["result"] or {}

            raise RuntimeError(
                data.get(
                    "error",
                    "Agent task failed"
                )
            )

        time.sleep(1)

    raise RuntimeError(
        "Agent task timed out while waiting for the local agent."
    )


def send_agent_message(message):

    result=api_request(
        "POST",
        "/agent/chat",
        {
            "message":message,
            "thread_id":st.session_state.thread_id
        }
    )

    st.session_state.thread_id=result["thread_id"]

    result=wait_for_task(
        result["task_id"]
    )

    load_chat_history()

    return result


def approve_agent(thread_id,approval):

    result=api_request(
        "POST",
        "/agent/approve",
        {
            "thread_id":thread_id,
            "approval":approval
        }
    )

    result=wait_for_task(
        result["task_id"]
    )

    load_chat_history()

    return result


st.title("🤖 Coding Agent")
st.caption(
    "AI coding agent powered by FastAPI + LangGraph + MCP"
)


with st.sidebar:

    st.subheader("Connection")

    st.session_state.api_url=st.text_input(
        "FastAPI URL",
        value=st.session_state.api_url
    )

    if st.session_state.token:

        st.success("Logged in")

        if st.session_state.user:
            st.write(
                f"User: {st.session_state.user['email']}"
            )

        st.divider()

        st.subheader("Chat History")

        if st.button(
            "Refresh Chat History",
            use_container_width=True
        ):
            try:
                load_chat_history()
                st.rerun()
            except Exception as e:
                st.error(str(e))

        if st.session_state.chat_history:

            for chat in st.session_state.chat_history:

                label=chat.get(
                    "preview",
                    ""
                ).strip()

                if not label or label=="Coding Agent":

                    if st.session_state.workspace_path:
                        label=Path(
                            st.session_state.workspace_path
                        ).name
                    else:
                        label="New Chat"

                label=label[:35]

                if st.button(
                    label,
                    key=f"history_{chat['thread_id']}",
                    use_container_width=True
                ):
                    try:
                        open_chat(
                            chat["thread_id"]
                        )
                    except Exception as e:
                        st.error(str(e))

        else:

            st.caption("No previous chats yet.")

        st.divider()

        st.subheader("Workspace")

        if st.session_state.workspace_path:

            st.success("Workspace selected")

            st.code(
                st.session_state.workspace_path,
                language=None
            )

        else:

            st.warning(
                "No project folder selected."
            )

        if st.button(
            "Select / Change Folder",
            use_container_width=True
        ):
            try:
                select_workspace()
            except Exception as e:
                st.error(str(e))

        if st.button(
            "Refresh Workspace",
            use_container_width=True
        ):
            try:
                refresh_workspace()
                st.rerun()
            except Exception as e:
                st.error(str(e))

        st.divider()

        if st.button(
            "New Chat",
            use_container_width=True
        ):
            st.session_state.thread_id=None
            st.session_state.messages=[]
            st.session_state.pending_approval=False
            st.session_state.approval_request=None
            st.session_state.latest_progress={}
            st.session_state.latest_changes=[]
            st.rerun()

        if st.button(
            "Logout",
            use_container_width=True
        ):
            st.session_state.token=None
            st.session_state.user=None
            st.session_state.workspace_path=None
            st.session_state.thread_id=None
            st.session_state.messages=[]
            st.session_state.pending_approval=False
            st.session_state.approval_request=None
            st.session_state.latest_progress={}
            st.session_state.latest_changes=[]
            st.session_state.chat_history=[]
            st.session_state.chat_history_loaded=False
            st.rerun()

    else:

        st.info(
            "Login first, then select your project folder."
        )


if not st.session_state.token:

    login_tab,register_tab,verify_tab=st.tabs(
        ["Login","Register","Verify OTP"]
    )

    with login_tab:

        st.subheader("Login")

        email=st.text_input(
            "Email",
            key="login_email"
        )

        password=st.text_input(
            "Password",
            type="password",
            key="login_password"
        )

        if st.button(
            "Login",
            type="primary"
        ):
            try:
                login(email,password)
                st.success("Login successful")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with register_tab:

        st.subheader("Create Account")

        email=st.text_input(
            "Email",
            key="register_email"
        )

        password=st.text_input(
            "Password",
            type="password",
            key="register_password"
        )

        if st.button("Register"):
            try:
                result=register(
                    email,
                    password
                )

                st.session_state.otp_email=email

                st.success(
                    result["message"]
                )

            except Exception as e:
                st.error(str(e))

    with verify_tab:

        st.subheader("Verify Email")

        email=st.text_input(
            "Email",
            value=st.session_state.get(
                "otp_email",
                ""
            ),
            key="verify_email"
        )

        otp=st.text_input(
            "OTP",
            max_chars=6,
            key="verify_otp"
        )

        if st.button("Verify OTP"):
            try:
                result=verify_otp(
                    email,
                    otp
                )

                st.success(
                    result["message"]
                )

            except Exception as e:
                st.error(str(e))

    st.stop()


if not st.session_state.chat_history_loaded:

    try:
        load_chat_history()
    except Exception:
        pass


if not st.session_state.workspace_path:

    st.subheader("Coding Workspace")

    st.warning(
        "Select your project folder from the sidebar before using the agent."
    )

    st.stop()


st.subheader("Coding Workspace")
st.caption(
    f"Workspace: {st.session_state.workspace_path}"
)


for message in st.session_state.messages:

    with st.chat_message(message["role"]):
        st.markdown(message["content"])


if st.session_state.latest_progress:

    with st.expander(
        "Agent Activity",
        expanded=True
    ):
        render_progress(
            st.session_state.latest_progress
        )


if st.session_state.latest_changes:
    render_changes(
        st.session_state.latest_changes
    )

prompt=st.chat_input(
    "Ask the coding agent to inspect or modify your project..."
)


if prompt:

    if st.session_state.pending_approval:
        st.warning(
            "Please approve or reject the pending tool call first."
        )
        st.stop()

    st.session_state.messages.append(
        {
            "role":"user",
            "content":prompt
        }
    )

    try:

        result=send_agent_message(prompt)

        if result.get("response"):

            response=result["response"]

            st.session_state.messages.append(
                {
                    "role":"assistant",
                    "content":response
                }
            )

        if result.get("approval_required"):

            st.session_state.pending_approval=True
            st.session_state.approval_request=result.get(
                "approval_request",
                "Approval required."
            )

        else:

            st.session_state.pending_approval=False
            st.session_state.approval_request=None

    except Exception as e:

        st.error(str(e))


if st.session_state.pending_approval:

    st.markdown("### ⚠️ Approval Required")

    st.warning(
        st.session_state.approval_request or
        "The agent wants to execute a protected tool."
    )

    col1,col2=st.columns(2)

    with col1:

        approve=st.button(
            "Approve",
            type="primary",
            key="pending_approve"
        )

    with col2:

        reject=st.button(
            "Reject",
            key="pending_reject"
        )

    if approve or reject:

        decision="yes" if approve else "no"

        try:

            result=approve_agent(
                st.session_state.thread_id,
                decision
            )

            if result.get("response"):

                st.session_state.messages.append(
                    {
                        "role":"assistant",
                        "content":result["response"]
                    }
                )

            if result.get("approval_required"):

                st.session_state.pending_approval=True
                st.session_state.approval_request=result.get(
                    "approval_request",
                    "Approval required."
                )

            else:

                st.session_state.pending_approval=False
                st.session_state.approval_request=None

            st.rerun()

        except Exception as e:
            st.error(str(e))
