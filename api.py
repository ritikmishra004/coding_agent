from fastapi import FastAPI,HTTPException,Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,EmailStr,Field
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sqlite3
import uuid
import json
from typing import Literal

from auth import (
    hash_password,
    verify_password,
    generate_otp,
    send_otp_email,
    create_access_token,
    get_current_user,
    DB_NAME
)



app=FastAPI(title="Coding Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


def init_agent_tasks_db():
    conn=sqlite3.connect(DB_NAME)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_tasks(
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            progress TEXT,
            result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    try:
        conn.execute(
            "ALTER TABLE agent_tasks ADD COLUMN progress TEXT"
        )
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def create_agent_task(user_id,task_type,payload):
    task_id=str(uuid.uuid4())
    now=datetime.now(timezone.utc).isoformat()

    conn=sqlite3.connect(DB_NAME)
    conn.execute(
        """
        INSERT INTO agent_tasks(
            id,user_id,task_type,payload,status,created_at,updated_at
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            task_id,
            user_id,
            task_type,
            json.dumps(payload),
            "pending",
            now,
            now
        )
    )
    conn.commit()
    conn.close()

    return task_id


def get_user_task(user_id,task_id):
    conn=sqlite3.connect(DB_NAME)
    task=conn.execute(
        """
        SELECT id,task_type,payload,status,progress,result
        FROM agent_tasks
        WHERE id=? AND user_id=?
        """,
        (task_id,user_id)
    ).fetchone()
    conn.close()
    return task


def get_chat_history(user_id):

    conn=sqlite3.connect(DB_NAME)

    rows=conn.execute(
        """
        SELECT
            id,
            task_type,
            payload,
            result,
            created_at,
            updated_at
        FROM agent_tasks
        WHERE user_id=?
          AND task_type IN ('chat','approve')
        ORDER BY created_at ASC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    chats={}

    for row in rows:

        payload=json.loads(row[2])
        result=json.loads(row[3]) if row[3] else {}

        thread_id=payload.get("thread_id")

        if not thread_id:
            continue

        if thread_id not in chats:

            workspace_path=payload.get(
                "workspace_path"
            )

            workspace_name="Coding Agent"

            if workspace_path:

                workspace_name=Path(
                    workspace_path
                ).name

            chats[thread_id]={
                "thread_id":thread_id,
                "workspace_name":workspace_name,
                "messages":[],
                "updated_at":row[5]
            }

        chat=chats[thread_id]
        chat["updated_at"]=row[5]

        if row[1]=="chat":

            message=payload.get("message")

            if message:

                chat["messages"].append(
                    {
                        "role":"user",
                        "content":message
                    }
                )

        elif row[1]=="approve":

            approval=payload.get("approval")

            if approval:

                chat["messages"].append(
                    {
                        "role":"user",
                        "content":(
                            "Approval: "
                            + approval
                        )
                    }
                )

        response=result.get("response")

        if response:

            chat["messages"].append(
                {
                    "role":"assistant",
                    "content":response
                }
            )

        if result.get("approval_required"):

            approval_request=result.get(
                "approval_request"
            )

            if approval_request:

                chat["messages"].append(
                    {
                        "role":"assistant",
                        "content":approval_request
                    }
                )

    return list(chats.values())


init_agent_tasks_db()


class AuthRequest(BaseModel):
    email:EmailStr
    password:str=Field(min_length=8)


class OTPRequest(BaseModel):
    email:EmailStr
    otp:str=Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$"
    )


class WorkspaceRequest(BaseModel):
    folder_path:str


class AgentRequest(BaseModel):
    message:str=Field(min_length=1)
    thread_id:str|None=None


class ApprovalRequest(BaseModel):
    thread_id:str
    approval:Literal["yes","no"]


@app.post("/auth/register")
def register(data:AuthRequest):
    conn=sqlite3.connect(DB_NAME)

    existing_user=conn.execute(
        "SELECT id FROM users WHERE email=?",
        (data.email,)
    ).fetchone()

    if existing_user:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    hashed_password=hash_password(data.password)
    otp=generate_otp()
    otp_hash=hash_password(otp)
    otp_expiry=(
        datetime.now(timezone.utc)+timedelta(minutes=5)
    )

    cursor=conn.execute(
        """
        INSERT INTO users(
            email,
            password_hash,
            is_verified,
            otp_hash,
            otp_expiry
        )
        VALUES(?,?,?,?,?)
        """,
        (
            data.email,
            hashed_password,
            0,
            otp_hash,
            otp_expiry.isoformat()
        )
    )

    user_id=cursor.lastrowid

    conn.commit()
    conn.close()

    send_otp_email(data.email,otp)

    return {
        "message":"Registration successful. Verify your OTP.",
        "user_id":user_id
    }


@app.post("/auth/verify-otp")
def verify_otp(data:OTPRequest):
    conn=sqlite3.connect(DB_NAME)

    user=conn.execute(
        """
        SELECT id,is_verified,otp_hash,otp_expiry
        FROM users
        WHERE email=?
        """,
        (data.email,)
    ).fetchone()

    if user is None:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if user[1]:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Email already verified"
        )

    if user[3] is None:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="OTP not found"
        )

    expiry=datetime.fromisoformat(user[3])

    if datetime.now(timezone.utc)>expiry:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="OTP expired"
        )

    if not verify_password(data.otp,user[2]):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )

    conn.execute(
        """
        UPDATE users
        SET is_verified=1,
            otp_hash=NULL,
            otp_expiry=NULL
        WHERE id=?
        """,
        (user[0],)
    )

    conn.commit()
    conn.close()

    return {"message":"Email verified successfully"}


@app.post("/auth/login")
def login(data:AuthRequest):
    conn=sqlite3.connect(DB_NAME)

    user=conn.execute(
        """
        SELECT id,email,password_hash,is_verified
        FROM users
        WHERE email=?
        """,
        (data.email,)
    ).fetchone()

    conn.close()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not verify_password(data.password,user[2]):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not user[3]:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email first"
        )

    token=create_access_token(user[0])

    return {
        "access_token":token,
        "token_type":"bearer"
    }


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return user


@app.post("/workspace/select")
def select_workspace(
    data:WorkspaceRequest,
    user=Depends(get_current_user)
):
    path=Path(data.folder_path).expanduser().resolve()

    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail="Folder does not exist"
        )

    if not path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Selected path is not a folder"
        )

    conn=sqlite3.connect(DB_NAME)

    conn.execute(
        """
        UPDATE users
        SET workspace_path=?
        WHERE id=?
        """,
        (str(path),user["id"])
    )

    conn.commit()
    conn.close()

    return {
        "message":"Workspace selected successfully",
        "workspace_path":str(path)
    }


@app.get("/workspace")
def get_workspace(user=Depends(get_current_user)):
    conn=sqlite3.connect(DB_NAME)

    workspace=conn.execute(
        """
        SELECT workspace_path
        FROM users
        WHERE id=?
        """,
        (user["id"],)
    ).fetchone()

    conn.close()

    return {
        "workspace_path":workspace[0] if workspace else None
    }


@app.get("/agent/chats")
def agent_chats(
    user=Depends(get_current_user)
):

    chats=get_chat_history(
        user["id"]
    )

    summaries=[]

    for chat in reversed(chats):

        summaries.append(
            {
                "thread_id":chat["thread_id"],
                "preview":chat.get(
                    "workspace_name",
                    "Coding Agent"
                ),
                "updated_at":chat["updated_at"]
            }
        )

    return {
        "chats":summaries
    }


@app.get("/agent/chats/{thread_id}")
def agent_chat_history(
    thread_id:str,
    user=Depends(get_current_user)
):

    chats=get_chat_history(
        user["id"]
    )

    for chat in chats:

        if chat["thread_id"]==thread_id:

            return chat

    raise HTTPException(
        status_code=404,
        detail="Chat not found"
    )

@app.post("/agent/chat")
def agent_chat(
    data:AgentRequest,
    user=Depends(get_current_user)
):
    thread_id=data.thread_id or str(uuid.uuid4())

    conn=sqlite3.connect(DB_NAME)

    workspace=conn.execute(
        """
        SELECT workspace_path
        FROM users
        WHERE id=?
        """,
        (user["id"],)
    ).fetchone()

    conn.close()

    if not workspace or not workspace[0]:
        raise HTTPException(
            status_code=400,
            detail="Please select a workspace first"
        )

    workspace_path=workspace[0]

    workspace_name=Path(workspace_path).name

    task_id=create_agent_task(
        user["id"],
        "chat",
        {
            "thread_id":thread_id,
            "message":data.message,
            "workspace_path":workspace_path,
            "workspace_name":workspace_name
        }
    )

    return {
        "task_id":task_id,
        "thread_id":thread_id,
        "status":"pending",
        "workspace_name":workspace_name
    }

@app.get("/agent/task/{task_id}")
def agent_task_status(
    task_id:str,
    user=Depends(get_current_user)
):
    task=get_user_task(user["id"],task_id)

    if task is None:
        raise HTTPException(status_code=404,detail="Task not found")

    progress=json.loads(task[4]) if task[4] else None
    result=json.loads(task[5]) if task[5] else None

    return {
        "task_id":task[0],
        "task_type":task[1],
        "status":task[3],
        "progress":progress,
        "result":result
    }


@app.post("/agent/approve")
def agent_approve(
    data:ApprovalRequest,
    user=Depends(get_current_user)
):
    task_id=create_agent_task(
        user["id"],
        "approve",
        {
            "thread_id":data.thread_id,
            "approval":data.approval
        }
    )

    return {
        "task_id":task_id,
        "thread_id":data.thread_id,
        "status":"pending"
    }


@app.get("/local-agent/tasks/next")
def local_agent_next_task(
    user=Depends(get_current_user)
):
    conn=sqlite3.connect(DB_NAME)

    try:
        conn.execute("BEGIN IMMEDIATE")

        task=conn.execute(
            """
            SELECT id,task_type,payload
            FROM agent_tasks
            WHERE user_id=? AND status='pending'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user["id"],)
        ).fetchone()

        if task is None:
            conn.commit()
            return {"task":None}

        now=datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE agent_tasks
            SET status='running',updated_at=?
            WHERE id=? AND user_id=? AND status='pending'
            """,
            (now,task[0],user["id"])
        )
        conn.commit()

        return {
            "task":{
                "id":task[0],
                "task_type":task[1],
                "payload":json.loads(task[2])
            }
        }

    finally:
        conn.close()


class AgentTaskProgress(BaseModel):
    progress:dict


@app.post("/local-agent/tasks/{task_id}/progress")
def local_agent_task_progress(
    task_id:str,
    data:AgentTaskProgress,
    user=Depends(get_current_user)
):
    conn=sqlite3.connect(DB_NAME)

    task=conn.execute(
        "SELECT progress FROM agent_tasks WHERE id=? AND user_id=?",
        (task_id,user["id"])
    ).fetchone()

    if task is None:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    existing_progress=json.loads(task[0]) if task[0] else {}

    if not isinstance(existing_progress,dict):
        existing_progress={}

    events=existing_progress.get("events",[])

    if not isinstance(events,list):
        events=[]

    events.append(data.progress)

    merged_progress={
        **existing_progress,
        **data.progress,
        "events":events[-100:]
    }

    now=datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        UPDATE agent_tasks
        SET progress=?,updated_at=?
        WHERE id=? AND user_id=?
        """,
        (
            json.dumps(merged_progress),
            now,
            task_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return {"message":"Progress saved"}


class AgentTaskResult(BaseModel):
    result:dict|None=None
    error:str|None=None


@app.post("/local-agent/tasks/{task_id}/result")
def local_agent_task_result(
    task_id:str,
    data:AgentTaskResult,
    user=Depends(get_current_user)
):
    conn=sqlite3.connect(DB_NAME)

    task=conn.execute(
        "SELECT id FROM agent_tasks WHERE id=? AND user_id=?",
        (task_id,user["id"])
    ).fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404,detail="Task not found")

    if data.error:
        status="failed"
        result_data={"error":data.error}
    elif data.result and data.result.get("approval_required"):
        status="awaiting_approval"
        result_data=data.result
    else:
        status="completed"
        result_data=data.result
    now=datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        UPDATE agent_tasks
        SET status=?,result=?,updated_at=?
        WHERE id=? AND user_id=?
        """,
        (
            status,
            json.dumps(result_data),
            now,
            task_id,
            user["id"]
        )
    )
    conn.commit()
    conn.close()

    return {"message":"Task result saved","status":status}
