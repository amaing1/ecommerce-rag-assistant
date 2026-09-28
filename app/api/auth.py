"""
认证接口：注册、登录

这个文件负责把昨天写的认证服务（app/services/auth.py）挂到 HTTP 接口上。
用户通过 HTTP 请求调用这些接口，完成注册和登录。
"""

# ============================================================
# 第 1 块：导入工具
# ============================================================

# APIRouter：创建路由，把接口挂到 FastAPI 上
# Depends：依赖注入，让 FastAPI 帮我们创建数据库会话
# HTTPException：主动报错，返回 HTTP 错误码给前端
# status：HTTP 状态码（比如 400、401、200）
from fastapi import APIRouter, Depends, HTTPException, status

# Session：数据库会话的类型提示
from sqlalchemy.orm import Session

# get_db：返回一个数据库会话，每次请求自动创建，用完自动关闭
from app.database import get_db

# User：用户表模型，用来查数据库里的用户
from app.models import User

# UserRegister：注册时前端发来的数据格式（username + email + password）
# UserLogin：登录时前端发来的数据格式（username + password）
# Token：登录成功后返回给前端的格式（access_token + token_type）
# UserResponse：注册成功后返回给前端的用户信息（不包含密码）
from app.schemas.auth import UserRegister, UserLogin, Token, UserResponse

# authenticate_user：验证用户名和密码是否正确
# create_access_token：登录成功后生成 JWT Token
# get_password_hash：注册时把明文密码加密成哈希密码
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
)

# 创建路由器
# prefix="/auth"：所有接口路径前面都加上 /auth
# tags=["认证"]：在 /docs 页面里归类到“认证”分组
router = APIRouter(prefix="/auth", tags=["认证"])


# ============================================================
# 第 2 块：注册接口
# ============================================================

@router.post("/register", response_model=UserResponse)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    用户注册接口

    流程：
        1. 检查用户名是否已被注册
        2. 检查邮箱是否已被注册
        3. 把密码加密成哈希密码
        4. 创建用户并存入数据库
        5. 返回用户信息（不返回密码）

    返回：UserResponse（id + username + email）
    """

    # 1. 检查用户名是否已被注册
    # db.query(User)：查 User 表
    # .filter(User.username == user_data.username)：筛选用户名匹配的
    # .first()：取第一条（用户名唯一，要么有一条，要么没有）
    existing_user = db.query(User).filter(User.username == user_data.username).first()

    # 如果 existing_user 有值，说明用户名已被占用
    if existing_user:
        # 返回 400 错误，告诉前端“用户名已被注册”
        raise HTTPException(status_code=400, detail="用户名已被注册")

    # 2. 检查邮箱是否已被注册
    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 3. 加密密码
    # get_password_hash：把明文密码变成哈希密码（$2b$12$...）
    hashed_password = get_password_hash(user_data.password)

    # 4. 创建用户并存入数据库
    # new_user = User(...)：创建一个新的 User 对象（内存中）
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password
    )

    # db.add()：告诉数据库会话“要新增这条数据”
    db.add(new_user)
    # db.commit()：正式提交事务，真正写入数据库
    db.commit()
    # db.refresh()：从数据库重新读取，获取自动生成的 id
    db.refresh(new_user)

    # 5. 返回用户信息（不返回密码）
    # UserResponse 只包含 id、username、email
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email
    )


# ============================================================
# 第 3 块：登录接口
# ============================================================

@router.post("/login", response_model=Token)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    用户登录接口

    流程：
        1. 验证用户名和密码
        2. 验证通过，生成 JWT Token
        3. 返回 Token

    返回：Token（access_token + token_type）
    """

    # 1. 验证用户名和密码
    # authenticate_user：去数据库查用户，验证密码
    # 如果验证失败，返回 None
    user = authenticate_user(db, user_data.username, user_data.password)

    # 如果 user 是 None，说明用户名或密码错误
    if not user:
        # 返回 401 错误（未授权）
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 生成 JWT Token
    # create_access_token：生成一个 JWT，里面存着用户名
    # data={"sub": user.username}：把用户名放进 Token 的 sub 字段
    access_token = create_access_token(data={"sub": user.username})

    # 3. 返回 Token
    # token_type="bearer"：告诉前端这是 Bearer Token，请求时放在 Authorization 头里
    return Token(access_token=access_token, token_type="bearer")


# ============================================================
# 第 4 块：游客一键体验接口（给演示/面试官用）
# ============================================================

# 演示账号固定配置。
# 第一次点击"一键体验"时自动创建，之后每次都复用同一账号，
# 所以同一个演示账号下的聊天记录会一直保留。
DEMO_USERNAME = "demo_user"
DEMO_EMAIL = "demo@ecommerce-rag.local"
DEMO_PASSWORD = "demo123456"


@router.post("/demo", response_model=Token)
def demo_login(db: Session = Depends(get_db)):
    """
    游客一键体验接口

    流程：
        1. 查找固定的演示账号 demo_user
        2. 不存在就自动创建（幂等：多次点击不会重复建号）
        3. 直接为该账号生成 JWT Token 并返回
        4. 前端拿到 Token 后免密进入系统

    注意：
        - 这个接口不校验密码，只服务于演示场景（想删随时可以删）
        - 登录/注册功能不受影响
    """

    # 1. 查找演示账号
    demo_user = db.query(User).filter(User.username == DEMO_USERNAME).first()

    # 2. 不存在就自动创建
    if not demo_user:
        demo_user = User(
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            hashed_password=get_password_hash(DEMO_PASSWORD)
        )
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)

    # 3. 生成 Token 并返回
    access_token = create_access_token(data={"sub": demo_user.username})
    return Token(access_token=access_token, token_type="bearer")





