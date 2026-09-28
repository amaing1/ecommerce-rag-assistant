"""
用户模型

这张表存的是“谁在用这个系统”。
对应数据库中的 users 表。
"""

# ============================================================
# 第1块：导入工具
# ============================================================

# 从 SQLAlchemy 中导入“列”和“字段类型”
# Column：定义表中的一列
# Integer：整数类型（用于 id）
# String：字符串类型（用于 username、email、password）
# DateTime：日期时间类型（用于 created_at、updated_at）
from sqlalchemy import Column, Integer, String, DateTime

# 从 SQLAlchemy 的 SQL 函数模块中导入 func
# func.now() 用于获取“当前时间”
from sqlalchemy.sql import func

# 从你的 database.py 中导入 Base（基类）
# 所有模型必须继承 Base，才能被 SQLAlchemy 识别为表
from app.database import Base


# ============================================================
# 第2块：定义 User 类（对应 users 表）
# ============================================================

class User(Base):
    """
    用户表
    继承 Base，表示这个类会被映射到数据库的一张表
    """

    # ---------- 2.1 表名 ----------
    __tablename__ = "users"
    """
    指定数据库中的表名为 "users"
    SQLAlchemy 在执行 CREATE TABLE 时，会创建名为 users 的表
    """

    # ---------- 2.2 字段定义 ----------

    id = Column(Integer, primary_key=True, index=True)
    """
    主键，自增整数
    - primary_key=True：每行数据的唯一标识
    - index=True：为这个字段创建索引，查询时更快
    """

    username = Column(String(50), unique=True, nullable=False, index=True)
    """
    用户名
    - String(50)：最多 50 个字符
    - unique=True：不能重复（两个用户不能同名）
    - nullable=False：不能为空（注册时必须填）
    - index=True：创建索引，按用户名查询更快
    """

    email = Column(String(100), unique=True, nullable=False)
    """
    邮箱
    - String(100)：最多 100 个字符
    - unique=True：不能重复
    - nullable=False：不能为空
    """

    hashed_password = Column(String(255), nullable=False)
    """
    加密后的密码
    - String(255)：最多 255 个字符（加密后的密码通常很长）
    - nullable=False：不能为空
    注意：存的是哈希值，不是明文密码
    """

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    """
    创建时间
    - DateTime(timezone=True)：带时区的日期时间
    - server_default=func.now()：插入数据时，数据库自动填当前时间
    """

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    """
    更新时间
    - DateTime(timezone=True)：带时区的日期时间
    - onupdate=func.now()：每次更新数据时，数据库自动更新为当前时间
    """

    # ---------- 2.3 关联关系 ----------
    # 注意：User 表是顶层表，不需要定义 relationship
    # 关联关系在子表（KnowledgeBase）中定义，通过 backref 反向关联
    # 这意味着 User 对象可以通过 .knowledge_bases 访问它所有的知识库

    # ---------- 2.4 调试方法 ----------
    def __repr__(self):
        """
        __repr__ 是 Python 的“魔法方法”
        作用：当你打印这个对象时，决定显示什么内容

        有 __repr__：
            print(user) → <User(id=1, username=test_user)>
        没有 __repr__：
            print(user) → <app.models.user.User object at 0x7f8a1c2d3e4f>

        前者一眼就能看到关键信息，后者只是一串内存地址
        主要用于调试，不影响数据库
        """
        return f"<User(id={self.id}, username={self.username})>"