from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# bcrypt 只处理前 72 个**字节**，超出部分会直接抛 ValueError
# （不是静默截断——bcrypt 5.0 起改为报错，避免"用户以为自己设了长密码"）。
#
# 关键坑：限制是**字节**不是字符。一个汉字在 UTF-8 下占 3 字节，
# 所以 25 个汉字的密码就有 75 字节，已经越界了。
# 只写 max_length=100（字符）根本挡不住，会一路走到 bcrypt 才炸成 500。
#
# 在 Schema 层拦下来，是为了把"服务端 500"变成"客户端 422 + 一句看得懂的提示"。
BCRYPT_MAX_BYTES = 72


def _check_password_byte_length(value: str) -> str:
    encoded = len(value.encode("utf-8"))
    if encoded > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"密码过长：最多 {BCRYPT_MAX_BYTES} 字节，当前 {encoded} 字节。"
            f"注意一个汉字占 3 字节（约 {BCRYPT_MAX_BYTES // 3} 个汉字封顶），"
            "纯英文数字则可以更长。"
        )
    return value


# ========== Auth ==========
class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)

    _validate_password_bytes = field_validator("password")(_check_password_byte_length)


class UserLogin(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)

    _validate_password_bytes = field_validator("new_password")(
        _check_password_byte_length
    )


class RefreshRequest(BaseModel):
    """刷新令牌请求。

    放在请求体而不是 query string —— query 会被 nginx access log、
    浏览器历史、Referer 头记录，等于把长期有效的 refresh token 到处撒。
    """
    refresh_token: str = Field(..., min_length=10)


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


class KbPermissionGrant(BaseModel):
    """授予某用户对某知识库的访问权限"""
    user_id: int
    # read  = 可检索；write = 额外可上传/删除该库文档
    permission: str = Field("read", pattern="^(read|write)$")