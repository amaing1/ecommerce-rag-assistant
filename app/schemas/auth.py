"""
认证相关的 Pydantic 模型（请求/响应）
"""

from typing import Optional  # 新增导入
from pydantic import BaseModel


class UserRegister(BaseModel):
    """用户注册请求体"""
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    """用户登录请求体"""
    username: str
    password: str


class Token(BaseModel):
    """登录成功返回的 Token 响应"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """JWT Token 中存储的用户数据"""
    username: Optional[str] = None   # 改成 Optional[str]


class UserResponse(BaseModel):
    """用户信息响应（不返回密码）"""
    id: int
    username: str
    email: str