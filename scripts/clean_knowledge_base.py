"""
知识库数据清洗脚本
==================
背景：mi.com 爬取的知识库 txt 里混入了网页导航噪音：
  - "来源：https://..." 的 URL 行（纯垃圾）
  - "颜色：" 字段里混入的导航词（到货通知/喜欢/官方微信/选购指南 等）
这些噪音被切进向量库后，会污染检索结果、拉低 RAG 质量。

清洗规则：
  1. 删除所有以 "来源：" 开头的行
  2. 对 "颜色：" 行，删除导航噪音词，保留真实的颜色和售后信息
     （7天无理由退货/15天免费换货/满69包邮 是有用信息，保留）

用法：python scripts/clean_knowledge_base.py
输出：小米商城数码产品知识库_干净版.txt（与原文件同目录）
"""

import re

# 源文件（脏数据）
SRC = r"C:\Users\Lenovo\Desktop\小米商城知识库_企业版\小米商城数码产品知识库.txt"
# 输出文件（干净数据）
DST = r"C:\Users\Lenovo\Desktop\小米商城知识库_企业版\小米商城数码产品知识库_干净版.txt"

# 导航噪音词（网页按钮/分类文字，不是商品信息）
NOISE_WORDS = [
    "敬请期待", "到货通知", "喜欢", "价格说明", "预约维修服务",
    "官方微信", "选购指南", "商品详情", "手机", "平板", "电视",
]


def clean():
    removed_url = 0
    cleaned_color = 0
    out_lines = []

    with open(SRC, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()

            # 规则1：删除"来源：URL"行
            if stripped.startswith("来源："):
                removed_url += 1
                continue

            # 规则2：清洗"颜色："行的导航词
            if stripped.startswith("颜色："):
                # 删除导航噪音词
                for w in NOISE_WORDS:
                    line = line.replace("/" + w, "").replace(w, "")
                # 删除网页图标对应的私有使用区字符（PUA，显示为乱码）
                line = re.sub(r"[\ue000-\uf8ff]", "", line)
                # 清理可能残留的连续斜杠
                while "//" in line:
                    line = line.replace("//", "/")
                cleaned_color += 1

            out_lines.append(line)

    with open(DST, "w", encoding="utf-8") as f:
        f.writelines(out_lines)

    print("✅ 清洗完成")
    print(f"  删除来源URL行: {removed_url}")
    print(f"  清洗颜色行: {cleaned_color}")
    print(f"  输出文件: {DST}")


if __name__ == "__main__":
    clean()