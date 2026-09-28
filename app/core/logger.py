import sys
from pathlib import Path
from loguru import logger

# 确保 logs 目录存在
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 移除默认 handler（防止重复打印）
logger.remove()

# 配置1：输出到终端（带颜色，方便调试）
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# 配置2：输出到文件（按天滚动，保留7天）
logger.add(
    LOG_DIR / "app_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="INFO",
    rotation="00:00",      # 每天午夜滚动
    retention="7 days",    # 保留7天
    encoding="utf-8",
)

__all__ = ["logger"]

