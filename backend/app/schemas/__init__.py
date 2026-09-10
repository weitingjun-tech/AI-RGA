from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ========== Auth ==========
class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)


class UserLogin(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str
    role: str


class UserInfo(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


# ========== Chat ==========
class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    query: str = Field(..., min_length=1, max_length=2000)


class SourceCitation(BaseModel):
    doc_id: int
    doc_name: str
    chunk_id: str
    text_snippet: str
    score: float


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    sources: Optional[list[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationList(BaseModel):
    conversations: list[ConversationResponse]
    total: int


# ========== Knowledge ==========
class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: Optional[str]
    file_size: Optional[int]
    chunk_count: int
    status: str
    uploaded_by: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentList(BaseModel):
    documents: list[DocumentResponse]
    total: int


class DocumentProcessStatus(BaseModel):
    id: int
    status: str
    chunk_count: int