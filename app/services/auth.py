

# ============================================================
# auth.py — 认证服务
# ============================================================
# 这个文件负责三件事：
#   1. 密码加密和验证（注册/登录时用）
#   2. 生成 JWT Token（登录成功时发）
#   3. 从 Token 中解析用户（验证请求时用）
# ============================================================

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from app.schemas.auth import TokenData


# ============================================================
# 配置：密码哈希 + JWT
# ============================================================

# 密码哈希上下文（使用 bcrypt 算法）
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,      # 显式指定 bcrypt 参数
    bcrypt__ident="2b",     # 强制使用 2b 格式
)

# 从 .env 读取 JWT 配置
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


# ============================================================
# 窗口 1：密码加密（注册时用）
# ============================================================

def get_password_hash(password: str) -> str:
    """
    对明文密码进行哈希加密
    调用时机：用户注册时
    输入：明文密码（如 "123456"）
    输出：加密后的哈希字符串（如 "$2b$12$..."）
    """
    return pwd_context.hash(password)


# ============================================================
# 窗口 2：密码验证（登录时用）
# ============================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码是否匹配哈希密码
    调用时机：用户登录时
    输入：明文密码 + 数据库中的哈希密码
    输出：True（匹配）或 False（不匹配）
    """
    return pwd_context.verify(plain_password, hashed_password)


# ============================================================
# 窗口 3：身份验证（登录时用）
# ============================================================

def authenticate_user(db: Session, username: str, password: str):
    """
    验证用户身份
    调用时机：用户登录时（由 login 接口调用）
    流程：
        1. 根据用户名查询用户
        2. 如果用户不存在 → 返回 None
        3. 如果密码不匹配 → 返回 None
        4. 验证通过 → 返回 User 对象
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ============================================================
# 窗口 4：生成 JWT Token（登录成功时用）
# ============================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    生成 JWT Token
    调用时机：用户登录成功后（由 login 接口调用）
    输入：要写入 Token 的数据（如 {"sub": "testuser"}）
    输出：JWT 字符串（如 "eyJhbGciOiJIUzI1NiIs..."）
    流程：
        1. 复制传入的数据
        2. 设置过期时间（默认 30 分钟）
        3. 用 SECRET_KEY 签名
        4. 返回 JWT 字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ============================================================
# 窗口 5：从 Token 中解析用户（验证请求时用）
# ============================================================

def get_current_user_from_token(db: Session, token: str) -> Optional[User]:
    """
    从 JWT Token 中解析出当前用户
    调用时机：需要验证用户身份时（由 deps.py 调用）
    流程：
        1. 解码 Token（验证签名 + 提取数据）
        2. 从 payload 中提取 username
        3. 根据 username 查询用户
        4. 返回 User 对象或 None
    """
    try:
        # 解码 Token（验证签名并提取 payload）
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        token_data = TokenData(username=username)
    except JWTError:
        # Token 无效（过期、篡改、格式错误）
        return None

    # 根据用户名查询用户
    user = db.query(User).filter(User.username == token_data.username).first()
    return user





















































