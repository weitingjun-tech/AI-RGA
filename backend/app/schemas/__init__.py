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
    # 指定检索的知识库 ID 列表；为空表示检索全部知识库
    kb_ids: Optional[list[int]] = None


class FeedbackRequest(BaseModel):
    """用户对某条回答的反馈"""
    feedback: str = Field(..., pattern="^(up|down)$")      # up=有帮助 down=没帮助
    reason: Optional[str] = Field(None, max_length=64)     # 不准确/不完整/过时/无关
    comment: Optional[str] = Field(None, max_length=500)   # 补充说明


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
    kb_id: Optional[int] = None
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


# ========== Knowledge Base ==========
class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)


class KnowledgeBaseResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    collection_name: str
    is_default: Optional[str]
    doc_count: int = 0
    chunk_count: int = 0
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class KnowledgeBaseList(BaseModel):
    bases: list[KnowledgeBaseResponse]
    total: int