"""
商品实时查询工具（Agent 工具调用）
缓存层 = Redis（product:price 哈希，TTL 7 天），由 fetch_price.py 定时刷新
"""
import json
import os
import redis
from langchain_openai import ChatOpenAI
from app.core.config import settings

# 用便宜快速的模型（qwen-turbo）做商品名归一化：中文商品名 → 标准英文名
_llm = ChatOpenAI(
    model=settings.DASHSCOPE_MODEL_ROUTER,
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    temperature=0,
)

# ===== 连接 Redis（企业里这些从配置/环境变量读，这里先写死方便跑通）=====
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# 项目根：用于降级时读 data/api_details.json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRICE_FILE = os.path.join(BASE_DIR, "data", "api_details.json")

# Redis 连接对象（decode_responses=True 让返回的是 str 而不是 bytes）
_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
PRICE_HASH_KEY = "product:price"


def _load_price_map():
    """从 Redis 读全部商品价格；Redis 不可用时降级读文件
    返回: (price_map, source)  source: "redis"=实时 或 "file"=文件旧价"""
    try:
        raw = _r.hgetall(PRICE_HASH_KEY)    ##从redis把product:price这张表整个取出来
    except Exception as e:
        print(f"⚠️ Redis 连接失败({e})，降级读取文件")
        return _load_from_file(), "file"    # Redis 挂了 → 降级读文件（旧价）
    if not raw:
        print("⚠️ Redis 中没有价格数据，降级读取文件")
        return _load_from_file(), "file"
    price_map = {}
    for name, value in raw.items():
        info = json.loads(value)
        price_map[name] = {"当前价": info.get("当前价",""),"市场价": info.get("市场价","")}
    return price_map, "redis"



def _load_from_file():
    """降级：Redis 不可用时读 data/api_details.json"""
    price_map = {}
    if not os.path.exists(PRICE_FILE):
        return price_map
    with open(PRICE_FILE,encoding="UTF-8") as f:
        raw = json.load(f)
    for pid,info in raw.items():
        name = info.get("产品名","").strip()
        if not name:
            continue
        price_map[name] = {"当前价": info.get("当前价",""),"市场价": info.get("市场价","")}
    return price_map


def _normalize(question: str) -> str:
    """用大模型从用户话里提取商品名，转成标准英文名（如：小米16 → Xiaomi 16）"""
    prompt = f"""你是商品名识别器。从用户问题里提取出商品名称，输出小米商城的标准英文商品名。
规则：
- 只输出商品名，不要任何其他文字
- 中文要转成英文标准名（小米→Xiaomi，红米/Redmi→REDMI）
- 中文后缀保持原样，不要翻译（如"至尊版"就是"至尊版"，不要写成Ultra；"定制版"就是"定制版"）
- 提取不到商品名就输出"无"
用户问题：{question}"""
    try:
        resp = _llm.invoke(prompt)
        name = resp.content.strip()
        if not name or name == "无":
            name = question
    except Exception:
        name = question   # 大模型失败就退回原话，不阻塞
    # 硬编码兜底：大模型偶尔不转英文，这里补一刀（覆盖最常见的中文品牌词）
    name = name.replace("小米", "Xiaomi ").replace("红米", "REDMI ")
    return name.strip()


def query_price(question: str):
    """从问题里识别商品名，返回价格；查不到返回 None
    返回: {"product": 商品名, "当前价":..., "市场价":..., "source": "redis"/"file"}"""
    price_map, source = _load_price_map()
    if not price_map:
        return None
    # 先用大模型把中文商品名归一化成英文
    name = _normalize(question).strip()
    name_lower = name.lower()
    # 1. 精确匹配（忽略大小写）
    for pname in price_map:
        if pname.lower() == name_lower:
            return {"product": pname, **price_map[pname], "source": source}
    # 2. 退化为包含匹配：商品名包含在归一化名字里（优先更长的商品名）
    for pname in sorted(price_map.keys(), key=len, reverse=True):
        if pname.lower() in name_lower:
            return {"product": pname, **price_map[pname], "source": source}
    # 3. 最后一层兜底：按"系列代号"模糊匹配
    #    从归一化名字里抠出字母+数字的系列代号（如 k80、15），
    #    找出所有含同一代号 且 后缀重叠最多（如"至尊版"）的候选
    import re
    codes = re.findall(r"[a-z]{1,6}\s?\d+", name_lower)   # 如 "k80"、"xiaomi 15"
    if codes:
        candidates = []
        for pname in price_map:
            pl = pname.lower().replace(" ", "")
            if any(c.replace(" ", "") in pl for c in codes):
                # 后缀重叠度：归一化名里的中文字（如"至尊版"）在商品名里出现几个
                overlap = sum(1 for ch in name_lower if '\u4e00' <= ch <= '\u9fff' and ch in pname.lower())
                candidates.append((pname, overlap))
        if candidates:
            # 后缀重叠最多的优先
            candidates.sort(key=lambda x: x[1], reverse=True)
            best = candidates[0][0]
            return {"product": best, **price_map[best], "source": source}
    return None




