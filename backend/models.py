import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SessionRequest(BaseModel):
    session_id: str


# ---------- Domain ----------
class ProfileCreate(BaseModel):
    workspace_id: str
    name: str
    genre: Optional[str] = None
    avatar: Optional[str] = None


class ConnectionCreate(BaseModel):
    profile_id: str
    platform: str
    account_name: Optional[str] = None


class ReleaseCreate(BaseModel):
    profile_id: str
    title: str
    release_date: str  # YYYY-MM-DD (Day 0)
    cover: Optional[str] = None
    description: Optional[str] = None


class ContentCreate(BaseModel):
    release_id: str
    title: str
    platform: str
    content_type: str
    url: Optional[str] = None
    published_at: Optional[str] = None
    thumbnail: Optional[str] = None


class AiInsightRequest(BaseModel):
    profile_id: str
    release_id: Optional[str] = None


class AiAskRequest(BaseModel):
    profile_id: str
    question: str


class ReportCreate(BaseModel):
    profile_id: str
    title: str
    release_ids: Optional[List[str]] = None


class CsvCommitRequest(BaseModel):
    profile_id: str
    platform: str
    release_title: str
    release_date: str
    mapping: Dict[str, str]
    rows: List[Dict[str, Any]]
    content_title: Optional[str] = None
    content_type: Optional[str] = "track"
