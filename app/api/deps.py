"""
认证依赖注入模块：提供 get_current_user「门卫」函数。

把它加到需要登录的接口参数里，会自动完成：
    1. 从请求头提取 JWT Token
    2. 验证 Token 是否有效（签名、过期时间）
    3. 从数据库查出当前用户
任何一步失败，接口直接返回 401。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.auth import get_current_user_from_token


# 为什么用 HTTPBearer 而不是 OAuth2PasswordBearer：
# 后者会让 Swagger 弹「用户名/密码」表单，而 /auth/login 只收 JSON，格式不匹配会报 422。
# auto_error=False：请求头缺 Authorization 时不自动报错，返回 None 由我们判断返回 401。
oauth2_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    从请求头提取 JWT Token，验证并返回当前用户。

    参数：
        credentials - 由 oauth2_scheme 提取的凭证对象，含 token 字符串
        db - 由 get_db 创建的数据库会话

    返回：User - 当前登录用户

    异常：HTTPException 401 - Token 缺失、无效、过期或用户不存在
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    user = get_current_user_from_token(db, token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user