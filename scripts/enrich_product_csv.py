"""
补全 商品信息_汇总.csv
======================
用 data/api_details.json 补全 CSV 的空字段：
- 市场价/原价：CSV 为空的，用 api 的市场价
- 版本：CSV 为空的，从该商品的所有 SKU 名里提取配置（如 8GB+256GB）合并
- 关键参数：新增一列"关键参数"，来自 api 的关键参数 JSON
匹配规则：CSV 商品名先去颜色/后缀词，再匹配 api 的产品名。
用法：python scripts/enrich_product_csv.py
"""

import csv
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = r"C:\Users\Lenovo\Desktop\小米商城知识库_企业版\商品信息_汇总.csv"
API_PATH = os.path.join(BASE_DIR, "data", "api_details.json")

# 颜色/后缀词（用于从 CSV 名称里剥离，尝试匹配 api 产品名）
# 注意：复合色（深灰色/浅灰色/深灰）必须完整列出，否则会被"灰色"拆坏
COLOR_WORDS = [
    "深灰色", "浅灰色", "深灰", "浅灰",
    "黑色", "白色", "银色", "蓝色", "灰色", "粉色", "金色", "紫色", "绿色",
    "青色", "橙色", "红色", "棕色", "黄色", "米色", "星岩黑", "云雾白",
    "冷雾蓝", "羽雾白", "天际蓝", "流沙紫", "冰川白", "暗影黑", "曜石黑",
    "晨曦金", "月光银", "迷雾黑", "青春版", "透明", "雅灰",
]


def strip_suffix(name: str) -> str:
    """去掉名称结尾的颜色/后缀词，尝试匹配商品名
    用正则匹配"结尾的颜色词"，避免"深灰色"被拆成"深"+"灰色"的 bug"""
    import re
    # 颜色词（含复合色），按长度倒序排列，优先匹配长的
    colors = sorted(COLOR_WORDS, key=len, reverse=True)
    # 反复剥掉结尾的颜色词，直到没有可剥的
    while True:
        removed = False
        for w in colors:
            if name.endswith(w):
                name = name[: -len(w)].strip()
                removed = True
                break
        if not removed:
            break
    return name.strip()


def extract_version(sku_name: str) -> str:
    """从 SKU 名里提取版本配置
    兼容两种格式：
    - "8GB+256GB"（英文+号）
    - "6GB内存 128GB存储"（中文描述）
    """
    import re
    # 格式1：8GB+256GB
    m = re.search(r"\d+\s*GB\s*\+\s*\d+\s*(?:GB|TB)", sku_name)
    if m:
        return m.group(0).replace(" ", "")
    # 格式2：6GB内存 128GB存储 → 转成 6GB+128GB
    m2 = re.search(r"(\d+\s*GB)内存\s*(\d+\s*(?:GB|TB))存储", sku_name)
    if m2:
        return m2.group(1).replace(" ", "") + "+" + m2.group(2).replace(" ", "")
    # 格式3：只有单个内存描述
    m3 = re.search(r"\d+\s*GB(?:\s*(?:运行)?内存)?(?:\s*\d+\s*(?:GB|TB))?", sku_name)
    return ""  # 提取不到就返回空（不强求）


def main():
    # 1. 读 CSV
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    if "关键参数" not in fieldnames:
        fieldnames.append("关键参数")

    # 2. 读 api_details
    with open(API_PATH, encoding="utf-8") as f:
        api = json.load(f)

    # 3. 建索引：商品名 → 数据；同时收集每个商品的所有 SKU（用于版本合并）
    api_by_name = {}
    sku_by_name = {}
    for pid, v in api.items():
        name = (v.get("产品名") or "").strip()
        if not name:
            continue
        api_by_name[name] = v
        sku = (v.get("SKU名") or "").strip()
        sku_by_name.setdefault(name, []).append(sku)

    # 4. 逐行补全
    matched = 0
    for r in rows:
        csv_name = r["商品名称"]
        # 找匹配的 api 商品
        api_key = csv_name
        if api_key not in api_by_name:
            api_key = strip_suffix(csv_name)
        v = api_by_name.get(api_key)
        if not v:
            continue
        matched += 1

        # 补市场价（CSV 为空才补）
        if not r.get("市场价/原价") or not r["市场价/原价"].strip():
            mprice = (v.get("市场价") or "").strip()
            if mprice:
                r["市场价/原价"] = mprice

        # 补版本：收集该商品所有 SKU 的配置，去重合并
        if not r.get("版本") or not r["版本"].strip():
            versions = []
            for sku in sku_by_name.get(api_key, []):
                ver = extract_version(sku)
                if ver and ver not in versions:
                    versions.append(ver)
            if versions:
                r["版本"] = "/".join(versions)

        # 补关键参数（新列）
        kp = v.get("关键参数")
        if kp:
            r["关键参数"] = json.dumps(kp, ensure_ascii=False)

    # 5. 写回
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # 6. 报告
    empty = {}
    for col in ["市场价/原价", "版本", "核心卖点", "颜色", "关键参数"]:
        empty[col] = sum(1 for r in rows if not r.get(col) or not r[col].strip())
    print(f"✅ 完成：匹配 {matched}/{len(rows)} 行，已写回 {CSV_PATH}")
    print(f"补全后空缺：{empty}")


if __name__ == "__main__":
    main()
