from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置类，所有配置从环境变量读取"""

    # 应用基础配置
    APP_NAME: str = Field(default="电商售后知识库智能问答助手", description="应用名称")
    DEBUG: bool = Field(default=False, description="调试模式")
    API_PORT: int = Field(default=8000, description="服务端口")

    # 数据库配置
    DATABASE_URL: str = Field(description="数据库连接地址")

    # LLM 配置
    DASHSCOPE_API_KEY: str = Field(description="百炼API密钥")
    DASHSCOPE_BASE_URL: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    DASHSCOPE_MODEL: str = Field(default="qwen-max")
    # ===== 模型分层：轻任务用 turbo（便宜快），重任务用 plus（质量好）=====
    DASHSCOPE_MODEL_ROUTER: str = Field(default="qwen-max", description="轻量任务模型：意图路由/数据清洗/评估")
    DASHSCOPE_MODEL_GENERATE: str = Field(default="qwen-plus", description="生成任务模型：最终答案")

    # 成本监控配置（单位：元/千token，按百炼当前价格填写，可自行调整）
    INPUT_PRICE_PER_1K: float = Field(default=0.0003, description="大模型输入价格(元/千token)")
    OUTPUT_PRICE_PER_1K: float = Field(default=0.0006, description="大模型输出价格(元/千token)")

    # 识图模型(qwen3-vl-plus)价格
    VISION_INPUT_PRICE_PER_1K: float = Field(default=0.0015, description="识图模型输入价格(元/千token)")
    VISION_OUTPUT_PRICE_PER_1K: float = Field(default=0.002, description="识图模型输出价格(元/千token)")




    # 检索配置
    CHUNK_SIZE: int = Field(default=500, description="文档分块大小")
    CHUNK_OVERLAP: int = Field(default=50, description="分块重叠大小")
    TOP_K: int = Field(default=5, description="检索返回的文档数量")
    MIN_SCORE: float = Field(default=0.3, description="来源阈值")

    # JWT 配置
    SECRET_KEY: str = Field(description="JWT 签名密钥，用于验证 Token 是否被篡改")
    ALGORITHM: str = Field(default="HS256", description="JWT 加密算法，建议保持 HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Token 过期时间（分钟）")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()




