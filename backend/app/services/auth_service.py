import bcrypt
from datetime import datetime, timedelta
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.config import JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_EXPIRE_MINUTES, JWT_REFRESH_EXPIRE_DAYS
from app.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def register_user(db: Session, username: str, password: str) -> User | None:
    if db.query(User).filter(User.username == username).first():
        return None
    user = User(username=username, password_hash=hash_password(password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def change_user_password(db: Session, user_id: int, old_password: str, new_password: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not verify_password(old_password, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    db.commit()
    return True


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def seed_admin(db: Session):
    """创建默认管理员 admin / 123456"""
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            password_hash=hash_password("123456"),
            role="admin",
        )
        db.add(admin)
        db.commit()