from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import logger  # 导入日志
from app.api import health,chat,knowledge,auth,monitor,monitor
from app.core.exception import register_exception_handlers
from app.database import engine, Base
from app.models import RetrievalLog  # noqa: F401 — 确保 Base.metadata 能找到此表
import os, sys, threading, time, subprocess  # ← 新增：定时刷新价格用
app = FastAPI(
    title=settings.APP_NAME,
    description="基于 RAG 的智能客服辅助系统",
    version="1.0.0"
)
# ===== 新增：注册全局异常处理器（必须在所有路由之前）=====
register_exception_handlers(app)
# =======================================================

# ===== 新增：价格定时刷新（后台线程，每 4 天自动刷一次）=====
# 原理：应用启动后，后台线程死循环每 4 天调用一次 scripts/fetch_price.py，
#       把小米商城最新价格刷进 Redis + 本地文件。
#       不需要 Windows 计划任务/密码/管理员权限，跨平台可用。
# 优化：启动时先检查 Redis 里价格是否 4 天内刷过（看 TTL），
#       刷过就跳过第一轮，避免"每次重启都刷一次"。
PRICE_REFRESH_INTERVAL = 4 * 24 * 3600  # 4 天（秒）
TTL_FRESH_THRESHOLD = 4 * 24 * 3600     # 4 天内算"新鲜"，不刷

def _redis_price_is_fresh() -> bool:
    """检查 Redis 价格是否 4 天内刷过：看 hash 的 TTL（刚刷完 TTL≈7天）"""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        ttl = r.ttl("product:price")
        if ttl and ttl > 0:
            return ttl > TTL_FRESH_THRESHOLD
        return False  # 无 TTL 或 key 不存在 → 视为不新鲜，需要刷
    except Exception as e:
        logger.warning(f"⚠️ 检查 Redis 价格新鲜度失败（{e}），按需要刷新处理")
        return False

def _price_refresh_loop():
    # 等 15 秒再开始（让 FastAPI 先完全启动，避免抢占资源）
    time.sleep(15)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base_dir, "scripts", "fetch_price.py")
    first_round = True   # 标记是否是启动后的第一轮
    while True:
        # 启动后的第一轮：如果 Redis 里价格还是新鲜的（4天内刷过），跳过
        if first_round and _redis_price_is_fresh():
            logger.info("⏭️ 启动检查：Redis 价格 4 天内已刷新，跳过本轮（4 天后再刷）")
        else:
            try:
                logger.info("🔄 开始自动刷新商品价格...")
                # 用 subprocess 调用独立脚本（和手动跑 python scripts/fetch_price.py 一样）
                result = subprocess.run(
                    [sys.executable, script],
                    cwd=base_dir,
                    capture_output=True, text=True, timeout=3600,
                )
                if result.returncode == 0:
                    logger.info(f"✅ 价格刷新完成（退出码 0）")
                else:
                    logger.error(f"❌ 价格刷新失败（退出码 {result.returncode}）：{result.stderr[-500:]}")
            except Exception as e:
                logger.error(f"❌ 价格刷新异常：{e}")
        first_round = False  # 第一轮结束，之后每轮都按 4 天周期刷
        # 睡 4 天，进入下一轮
        time.sleep(PRICE_REFRESH_INTERVAL)

# 启动后台线程（daemon=True：主程序退出时线程自动结束）
_price_thread = threading.Thread(target=_price_refresh_loop, daemon=True)
_price_thread.start()
logger.info("⏰ 价格自动刷新线程已启动（每 4 天一次）")
# =======================================================

# 自动建表(幂等：已存在的表会跳过)
Base.metadata.create_all(bind=engine)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

###注册路由
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(auth.router)
app.include_router(monitor.router)
app.include_router(monitor.router)

# ---------- 日志中间件（记录每个请求）----------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"← {request.method} {request.url.path} → {response.status_code}")
    return response



# ---------- 启动日志 ----------
logger.info(f"🚀 {settings.APP_NAME} 启动中...")
logger.info(f"📝 调试模式: {settings.DEBUG}")
logger.info(f"🔑 模型: {settings.DASHSCOPE_MODEL}")