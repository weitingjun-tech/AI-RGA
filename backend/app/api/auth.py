"""认证相关 API"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserInfo,
    ChangePassword,
    RefreshRequest,
)
from app.services.auth_service import (
    register_user,
    authenticate_user,
    change_user_password,
    create_access_token,
    create_refresh_token,
)
from app.middleware.auth import get_current_user
from app.models.user import User
from app.services.audit_service import audit_log
from app.utils.rate_limit import (
    ip_rate_limit,
    client_ip,
    is_account_locked,
    record_login_failure,
    clear_login_failures,
)
from app.config import (
    RATE_LIMIT_LOGIN,
    RATE_LIMIT_REGISTER,
    LOGIN_MAX_FAILURES,
    LOGIN_LOCKOUT_MINUTES,
)

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(ip_rate_limit("register", RATE_LIMIT_REGISTER))],
)
def register(data: UserRegister, db: Session = Depends(get_db)):
    """用户注册（按 IP 限流，防批量注册）"""
    user = register_user(db, data.username, data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    audit_log(db, user, "auth.register", detail={"username": user.username})

    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        username=user.username,
        role=user.role,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(ip_rate_limit("login", RATE_LIMIT_LOGIN))],
)
def login(request: Request, data: UserLogin, db: Session = Depends(get_db)):
    """用户登录。

    两道防线：
      1. 按 IP 限流 —— 挡住"一个 IP 狂试很多账号"
      2. 按账号锁定 —— 挡住"很多 IP 一起试同一个账号"（撞库）
    单靠任何一个都有绕过的办法，两个一起才能把暴力破解的成本抬起来。
    """
    if is_account_locked(data.username, LOGIN_MAX_FAILURES):
        audit_log(
            db, None, "auth.login_blocked",
            detail={"username": data.username}, status="failure", ip=client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"该账号连续登录失败次数过多，已锁定 {LOGIN_LOCKOUT_MINUTES} 分钟",
        )

    user = authenticate_user(db, data.username, data.password)
    if user is None:
        failures = record_login_failure(data.username, LOGIN_LOCKOUT_MINUTES)
        # 审计用的是**提交上来的用户名**，不是用户对象——失败时根本不知道是谁
        audit_log(
            db, None, "auth.login_failed",
            detail={"username": data.username, "consecutive_failures": failures},
            status="failure", ip=client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    clear_login_failures(data.username)
    audit_log(
        db, user, "auth.login", detail={"username": user.username}, ip=client_ip(request),
    )

    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        username=user.username,
        role=user.role,
    )


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user


@router.post("/change-password")
def change_password(
    data: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码"""
    ok = change_user_password(db, current_user.id, data.old_password, data.new_password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码错误")
    return {"message": "密码修改成功"}


@router.post("/refresh")
def refresh_token(data: RefreshRequest, db: Session = Depends(get_db)):
    """刷新 access token。

    refresh_token 从请求体读取（历史版本用 query 参数，会把长期令牌写进
    访问日志与浏览器历史，已改为请求体）。
    """
    from app.services.auth_service import decode_token
    payload = decode_token(data.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token无效")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}