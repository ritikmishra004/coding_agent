from fastapi import FastAPI,HTTPException,Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,EmailStr,Field
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sqlite3

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
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


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

    otp_expiry=datetime.now(
        timezone.utc
    )+timedelta(minutes=5)

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

    send_otp_email(
        data.email,
        otp
    )

    return {
        "message":"Registration successful. Verify your OTP.",
        "user_id":user_id
    }


@app.post("/auth/verify-otp")
def verify_otp(data:OTPRequest):

    conn=sqlite3.connect(DB_NAME)

    user=conn.execute(
        """
        SELECT
            id,
            is_verified,
            otp_hash,
            otp_expiry
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

    expiry=datetime.fromisoformat(
        user[3]
    )

    if datetime.now(timezone.utc)>expiry:
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="OTP expired"
        )

    if not verify_password(
        data.otp,
        user[2]
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )

    conn.execute(
        """
        UPDATE users
        SET
            is_verified=1,
            otp_hash=NULL,
            otp_expiry=NULL
        WHERE id=?
        """,
        (user[0],)
    )

    conn.commit()
    conn.close()

    return {
        "message":"Email verified successfully"
    }


@app.post("/auth/login")
def login(data:AuthRequest):

    conn=sqlite3.connect(DB_NAME)

    user=conn.execute(
        """
        SELECT
            id,
            email,
            password_hash,
            is_verified
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

    if not verify_password(
        data.password,
        user[2]
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not user[3]:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email first"
        )

    token=create_access_token(
        user[0]
    )

    return {
        "access_token":token,
        "token_type":"bearer"
    }


@app.get("/auth/me")
def me(
    user=Depends(get_current_user)
):
    return user


@app.post("/workspace/select")
def select_workspace(
    data:WorkspaceRequest,
    user=Depends(get_current_user)
):
    path=Path(
        data.folder_path
    ).expanduser().resolve()

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
        (
            str(path),
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return {
        "message":"Workspace selected successfully",
        "workspace_path":str(path)
    }


@app.get("/workspace")
def get_workspace(
    user=Depends(get_current_user)
):
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
        "workspace_path":(
            workspace[0]
            if workspace
            else None
        )
    }