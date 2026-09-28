# -*- coding: utf-8 -*-
"""
小米商城价格刷新脚本（定时任务用）
============================================================
作用：把 data/api_details.json 里每个商品的"当前价/市场价"刷新成最新值。
      供「商品实时查询工具(product_service.py)」读取，是价格的缓存层。

运行：python scripts/fetch_price.py [limit]
      limit 可选，只刷新前 N 个商品（调试用）

定时：Windows「任务计划程序」每 4~5 天跑一次本脚本即可（见 README）。

说明：
  真实企业中，这一层应替换为"直接调用企业内部商品价格 API / 定时同步数据库"；
  这里通过小米商城公开接口模拟"外部实时价格数据源"。
  架构不变：定时刷新缓存 → 查询工具读缓存。
"""
from playwright.sync_api import sync_playwright
import json, os, io, sys, time
import redis
# ===== 相对路径：以项目根目录为基准，不写死盘符 =====
# 本项目里所有脚本统一用这种写法（见 batch_upload.py），换机器也能跑
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRICE_FILE = os.path.join(DATA_DIR, "api_details.json")
# ===== Redis 连接（和 product_service.py 保持一致）=====
_r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")), db=0, decode_responses=True)
PRICE_HASH_KEY = "product:price"
TTL_SECONDS = 7 * 24 * 3600        # 7 天（> 4~5 天刷新周期，不会中途过期）

def safe_print(s):
    """打印时避免 Windows 控制台编码问题"""
    try:
        print(s, flush=True)
    except Exception:
        print("...", flush=True)


def parse_api(text):
    """解析小米 product/view API 返回的 JSONP/JSON，只提取价格相关字段"""
    txt = text.strip()
    if txt.startswith("("):
        txt = txt[1:-1]
    obj = json.loads(txt)
    if obj.get("code") != 200:
        return None
    data = obj.get("data") or {}
    rec = {}
    pi = data.get("product_info") or {}
    rec["产品名"] = pi.get("name", "")
    rec["产品描述"] = (pi.get("product_desc") or "").replace("<br/>", " ").replace("<br>", " ")
    gl = data.get("goods_list") or []
    if gl:
        gi = gl[0].get("goods_info") or {}
        rec["SKU名"] = gi.get("name", "")
        rec["当前价"] = gi.get("price")
        rec["市场价"] = gi.get("market_price")
        cp = gi.get("class_parameters") or {}
        params = {}
        for it in cp.get("list", []):
            k = it.get("name") or it.get("top_title") or ""
            v = it.get("value") or it.get("bottom_title") or ""
            if k and v and k not in params:
                params[k] = v
        rec["关键参数"] = params
    return rec


def load_pids():
    """从现有 api_details.json 读出所有商品 pid（只刷新已爬过的商品）"""
    if not os.path.exists(PRICE_FILE):
        safe_print("❌ 未找到 data/api_details.json，请先运行一次抓取")
        return []
    with io.open(PRICE_FILE, encoding="utf-8") as f:
        return list(json.load(f).keys())


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pids = load_pids()
    if not pids:
        return
    safe_print(f"共有 {len(pids)} 个商品待刷新{'（前 ' + str(limit) + ' 个）' if limit else ''}")

    # 读现有数据，逐商品覆盖价格字段
    results = {}
    if os.path.exists(PRICE_FILE):
        with io.open(PRICE_FILE, encoding="utf-8") as f:
            results = json.load(f)

    updated = 0
    failed = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # 打开一次首页建立会话（小米价格 API 需要浏览器会话 cookie）
        page.goto("https://www.mi.com/shop", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        for idx, pid in enumerate(pids):
            if limit and idx >= limit:
                break
            try:
                txt = page.evaluate("""async (pid) => {
                  const r = await fetch('https://api2.order.mi.com/product/view?product_id=' + pid + '&version=2', {credentials: 'include'});
                  return await r.text();
                }""", pid)
                rec = parse_api(txt)
                if rec:
                    results[pid] = rec
                    updated += 1
                    # ===== 写 Redis：商品名 → {当前价, 市场价} =====
                    name = rec.get("产品名","").strip()
                    if name and rec.get("当前价"):
                        _r.hset(PRICE_HASH_KEY, name,
                                json.dumps({"当前价": rec["当前价"], "市场价": rec.get("市场价", "")},
                                           ensure_ascii=False))  ###hset 的规则是：key 存在就覆盖，不存在就新建
                    safe_print(f"[{updated}] {pid} {rec.get('产品名','')[:30]} 价={rec.get('当前价')}")
                else:
                    failed += 1
                    safe_print(f"[SKIP] {pid} API 无数据（可能会话失效）")
            except Exception as e:
                failed += 1
                safe_print(f"[ERR] {pid} {e}")
            time.sleep(0.3)
            # 每刷一个就落盘，中断也不丢已刷新结果
            with io.open(PRICE_FILE, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)

        browser.close()

    # 给整个价格表设过期时间（保鲜期 7 天）
    _r.expire(PRICE_HASH_KEY,TTL_SECONDS)
    # ===== 下架商品清理：只在全量刷新（limit=0）时执行，防止部分刷新误删 =====
    if not limit:
        # 这次从 API 成功刷到的商品名集合
        fresh_names = {rec.get("产品名","").strip() for rec in results.values() if rec.get("产品名")}
        #  redis里所有的商品名
        redis_names = set(_r.hkeys(PRICE_HASH_KEY))
        ## 找出"redis中有，但这次API中没有的" = 已下架
        removed = redis_names - fresh_names
        if removed:
            for n in removed:
                _r.hdel(PRICE_HASH_KEY,n)
            safe_print(f"已清理 {len(removed)} 个下架商品: {list(removed)[:10]}...")
    safe_print(f"\n完成：成功 {updated} 个，失败 {failed} 个")
    safe_print(f"数据已写入 {PRICE_FILE}")


if __name__ == "__main__":
    main()




















