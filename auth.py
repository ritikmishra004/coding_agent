import sqlite3
import os
import secrets
import jwt
from datetime import datetime,timedelta,timezone
from dotenv import load_dotenv
from pwdlib import PasswordHash
from fastapi import HTTPException,Depends
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError

load_dotenv()

SECRET_KEY=os.getenv("JWT_SECRET_KEY")
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
DB_NAME="auth.db"

password_hash=PasswordHash.recommended()
security=HTTPBearer()

def init_db():
    conn=sqlite3.connect(DB_NAME)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0,
            otp_hash TEXT,
            otp_expiry TEXT
        )
    """)

    conn.commit()
    conn.close()

def hash_password(password):
    return password_hash.hash(password)

def verify_password(password,hashed_password):
    return password_hash.verify(password,hashed_password)

def generate_otp():
    return str(secrets.randbelow(900000)+100000)

def create_access_token(user_id):
    expire=datetime.now(timezone.utc)+timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload={
        "sub":str(user_id),
        "exp":expire
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def get_current_user(
    credentials:HTTPAuthorizationCredentials=Depends(security)
):
    token=credentials.credentials

    try:
        payload=jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id=payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid token"
            )

    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    conn=sqlite3.connect(DB_NAME)
    conn.row_factory=sqlite3.Row

    user=conn.execute(
        "SELECT id,email FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    return dict(user)

init_db()