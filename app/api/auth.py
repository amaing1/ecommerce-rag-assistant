"""
认证接口：注册、登录
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas.auth import UserRegister, UserLogin, Token, UserResponse
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
)

router = APIRouter(prefix="/auth", tags=["认证"])


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
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已被注册")

    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    hashed_password = get_password_hash(user_data.password)

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email
    )


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
    user = authenticate_user(db, user_data.username, user_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token, token_type="bearer")


# 演示账号固定配置。第一次点击"一键体验"时自动创建，之后复用同一账号，
# 所以同一演示账号下的聊天记录会一直保留。
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
    demo_user = db.query(User).filter(User.username == DEMO_USERNAME).first()

    if not demo_user:
        demo_user = User(
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            hashed_password=get_password_hash(DEMO_PASSWORD)
        )
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)

    access_token = create_access_token(data={"sub": demo_user.username})
    return Token(access_token=access_token, token_type="bearer")