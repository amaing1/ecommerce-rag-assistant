"""
认证依赖注入模块（门卫）

这个文件的作用：提供一个 "门卫" 函数 `get_current_user`，
把它加到需要登录的接口参数中，就能自动完成以下三件事：
    1. 从请求头中提取 JWT Token
    2. 验证 Token 是否有效（签名、过期时间）
    3. 从数据库查出当前用户

如果任何一步失败，接口直接返回 401，不会执行后续业务逻辑。
"""

# ============================================================
# 第 1 块：导入 FastAPI 核心工具
# ============================================================

# Depends：依赖注入。告诉 FastAPI："这个参数你不用前端传，你去执行另一个函数，把结果给我。"
# HTTPException：主动报错。如果门卫发现用户没登录，就抛出 401 错误，阻止请求继续。
# status：HTTP 状态码。比如 status.HTTP_401_UNAUTHORIZED 就是 401。
from fastapi import Depends, HTTPException, status

# ============================================================
# 第 2 块：导入 Token 提取工具（关键修改点）
# ============================================================

# HTTPBearer：专门从请求头中提取 Bearer Token 的工具。
# 前端请求格式：Authorization: Bearer <token>
# 这个工具会自动把 <token> 提取出来，你不需要手动解析请求头。
#
# 为什么不用 OAuth2PasswordBearer？
# 因为 OAuth2PasswordBearer 会让 Swagger 弹出一个"用户名/密码"表单，
# 但你的 /auth/login 接口只接收 JSON，格式不匹配会报 422。
# HTTPBearer 的 Swagger 弹窗是"直接输入 Token 字符串"，和你的登录接口完美配合。
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ============================================================
# 第 3 块：导入数据库相关
# ============================================================

# Session：类型提示，告诉 IDE 和检查工具 db 是数据库会话类型。
from sqlalchemy.orm import Session

# get_db：你之前在 database.py 里写的函数，用来创建数据库会话。
# 门卫查用户信息时需要用到它。
from app.database import get_db

# ============================================================
# 第 4 块：导入你自己的模块
# ============================================================

# User：用户表模型，门卫查到的用户信息会用它来返回。
from app.models import User

# get_current_user_from_token：你昨天写的服务函数！
# 它负责：解码 Token → 验证签名 → 提取用户名 → 从数据库查用户。
# 今天的门卫就是直接调用这个现成的工具。
from app.services.auth import get_current_user_from_token


# ============================================================
# 第 5 块：初始化 Token 提取器（关键修改点）
# ============================================================

# 创建一个 "提取器" 实例。
# auto_error=False 的意思是：如果请求头里没有 Authorization 字段，
# 不会自动报错，而是返回 None，由我们自己判断并返回 401。
#
# 之前用 OAuth2PasswordBearer(tokenUrl="/auth/login")，
# 会让 Swagger 弹"用户名/密码"表单，和你的 JSON 登录接口不兼容。
oauth2_scheme = HTTPBearer(auto_error=False)


# ============================================================
# 第 6 块：定义门卫函数（核心）
# ============================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    从请求头中提取 JWT Token，验证并返回当前用户。

    这个函数会被添加到需要登录才能访问的接口中。
    格式：current_user: User = Depends(get_current_user)

    执行流程：
        1. FastAPI 自动从请求头中提取 Token（通过 oauth2_scheme）
        2. FastAPI 自动创建数据库会话（通过 get_db）
        3. 调用 get_current_user_from_token 验证 Token 并查用户
        4. 如果用户不存在或 Token 无效，返回 401
        5. 验证通过，返回 User 对象给接口函数

    参数：
        credentials: HTTPAuthorizationCredentials - 由 oauth2_scheme 提取的凭证对象，包含 token 字符串
        db: Session - 由 get_db 创建的数据库会话

    返回：
        User - 当前登录的用户对象

    异常：
        HTTPException 401 - 未提供 Token、Token 无效、过期、或用户不存在
    """

    # 第 7 块：检查是否提供了 Token
    # HTTPBearer(auto_error=False) 在没带 Token 时不会自动报错，
    # 而是返回 None。这里需要自己判断并返回 401。
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 从 credentials 中取出 token 字符串
    token = credentials.credentials

    # 第 8 块：执行验证
    # 调用你昨天写的服务函数，传入 Token 和数据库会话。
    # 如果 Token 有效、用户存在，返回 User 对象；否则返回 None。
    user = get_current_user_from_token(db, token)

    # 如果返回的是 None（说明用户不存在、Token 过期或被篡改）
    if not user:
        # 第 9 块：报错处理
        # 抛出 401 异常，阻止请求继续执行。
        # headers={"WWW-Authenticate": "Bearer"} 告诉前端：
        # "你需要用 Bearer Token 的方式重新认证。"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 第 10 块：放行
    # 所有检查通过，把 User 对象返回给接口函数。
    # 接口函数里就可以直接用 current_user.id、current_user.username 了。
    return user



















































