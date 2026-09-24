import getpass
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from graph import run_agent

CONFIG_DIR=Path.home()/".coding_agent"
CONFIG_FILE=CONFIG_DIR/"config.json"
POLL_INTERVAL=1
DEFAULT_API_URL="http://127.0.0.1:8000"


def api_request(api_url,token,method,path,payload=None):

    url=f"{api_url.rstrip('/')}{path}"
    body=None

    headers={
        "Content-Type":"application/json"
    }

    if token:
        headers["Authorization"]=f"Bearer {token}"

    if payload is not None:
        body=json.dumps(payload).encode()

    request=urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            raw=response.read().decode()

            return json.loads(raw) if raw else {}

    except urllib.error.HTTPError as e:

        raw=e.read().decode()

        try:
            data=json.loads(raw)
        except json.JSONDecodeError:
            data={"detail":raw}

        raise RuntimeError(
            data.get(
                "detail",
                "Request failed"
            )
        )

    except urllib.error.URLError as e:

        raise RuntimeError(
            f"Cannot connect to API: {e.reason}"
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


def save_config(api_url,token,user_id,workspace_path):

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    CONFIG_FILE.write_text(
        json.dumps(
            {
                "api_url":api_url,
                "token":token,
                "user_id":user_id,
                "workspace_path":workspace_path
            },
            indent=2
        )
    )


def load_config():

    if not CONFIG_FILE.exists():
        return {}

    try:
        return json.loads(
            CONFIG_FILE.read_text()
        )

    except Exception:
        return {}


def login(api_url):

    email=input("Email: ").strip()
    password=getpass.getpass("Password: ")

    result=api_request(
        api_url,
        None,
        "POST",
        "/auth/login",
        {
            "email":email,
            "password":password
        }
    )

    token=result["access_token"]

    user=api_request(
        api_url,
        token,
        "GET",
        "/auth/me"
    )

    return token,user["id"]


def get_server_workspace(api_url,token):

    result=api_request(
        api_url,
        token,
        "GET",
        "/workspace"
    )

    workspace_path=result.get(
        "workspace_path"
    )

    if workspace_path and os.path.isdir(
        workspace_path
    ):
        return os.path.abspath(
            os.path.expanduser(workspace_path)
        )

    return None


def select_and_save_workspace(
    api_url,
    token,
    config
):

    workspace_path=choose_folder()

    if not workspace_path:
        raise RuntimeError(
            "No workspace folder selected."
        )

    result=api_request(
        api_url,
        token,
        "POST",
        "/workspace/select",
        {
            "folder_path":workspace_path
        }
    )

    workspace_path=result["workspace_path"]

    save_config(
        api_url,
        token,
        config["user_id"],
        workspace_path
    )

    return workspace_path


def get_workspace(api_url,token,config):

    workspace_path=get_server_workspace(
        api_url,
        token
    )

    if workspace_path:
        return workspace_path

    workspace_path=config.get(
        "workspace_path"
    )

    if workspace_path and os.path.isdir(
        workspace_path
    ):
        workspace_path=os.path.abspath(
            os.path.expanduser(workspace_path)
        )

        api_request(
            api_url,
            token,
            "POST",
            "/workspace/select",
            {
                "folder_path":workspace_path
            }
        )

        return workspace_path

    return select_and_save_workspace(
        api_url,
        token,
        config
    )


def report_task_progress(
    api_url,
    token,
    task_id,
    progress
):

    try:
        api_request(
            api_url,
            token,
            "POST",
            f"/local-agent/tasks/{task_id}/progress",
            {"progress":progress}
        )

    except Exception as e:

        print(
            f"[local-agent] Progress update failed: {e}"
        )


def process_task(
    api_url,
    token,
    user_id,
    workspace_path,
    task
):

    task_id=task["id"]
    task_type=task["task_type"]
    payload=task["payload"]

    print(
        f"\n[local-agent] Processing "
        f"{task_type}: {task_id}"
    )

    def progress_callback(progress):

        print(
            f"[local-agent] "
            f"{progress.get('message','Working...')}"
        )

        report_task_progress(
            api_url,
            token,
            task_id,
            progress
        )

    try:

        if task_type=="chat":

            result=run_agent(
                user_id=user_id,
                thread_id=payload["thread_id"],
                user_input=payload["message"],
                workspace_path=workspace_path,
                progress_callback=progress_callback
            )

        elif task_type=="approve":

            result=run_agent(
                user_id=user_id,
                thread_id=payload["thread_id"],
                approval=payload["approval"],
                workspace_path=workspace_path,
                progress_callback=progress_callback
            )

        else:

            raise ValueError(
                f"Unknown task type: {task_type}"
            )

        api_request(
            api_url,
            token,
            "POST",
            f"/local-agent/tasks/{task_id}/result",
            {"result":result}
        )

        if result.get("approval_required"):

            print(
                f"[local-agent] Waiting for approval: {task_id}"
            )

        else:

            print(
                f"[local-agent] Task completed: {task_id}"
            )

    except Exception as e:

        api_request(
            api_url,
            token,
            "POST",
            f"/local-agent/tasks/{task_id}/result",
            {"error":str(e)}
        )

        print(
            f"[local-agent] Task failed: {e}"
        )


def main():

    config=load_config()

    api_url=config.get("api_url") or input(
        f"API URL [{DEFAULT_API_URL}]: "
    ).strip() or DEFAULT_API_URL

    token=config.get("token")
    user_id=config.get("user_id")

    if token:

        try:

            user=api_request(
                api_url,
                token,
                "GET",
                "/auth/me"
            )

            user_id=user["id"]

        except Exception:

            print(
                "Saved login expired or is invalid. "
                "Please login again."
            )

            token,user_id=login(api_url)

    else:

        token,user_id=login(api_url)

    config["user_id"]=user_id

    workspace_path=get_workspace(
        api_url,
        token,
        config
    )

    save_config(
        api_url,
        token,
        user_id,
        workspace_path
    )

    print("="*60)
    print("Coding Agent Local Agent")
    print(f"User ID: {user_id}")
    print(f"Workspace: {workspace_path}")
    print(f"Cloud API: {api_url}")
    print("Waiting for agent tasks...")
    print("="*60)

    while True:

        try:

            response=api_request(
                api_url,
                token,
                "GET",
                "/local-agent/tasks/next"
            )

            task=response.get("task")

            if task:

                latest_workspace=get_server_workspace(
                    api_url,
                    token
                )

                if latest_workspace:
                    workspace_path=latest_workspace

                save_config(
                    api_url,
                    token,
                    user_id,
                    workspace_path
                )

                process_task(
                    api_url,
                    token,
                    user_id,
                    workspace_path,
                    task
                )

            else:

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:

            print("\nLocal agent stopped.")
            break

        except Exception as e:

            print(
                f"[local-agent] {e}"
            )

            time.sleep(3)


if __name__=="__main__":
    main()
