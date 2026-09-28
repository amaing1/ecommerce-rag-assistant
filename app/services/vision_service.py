from langchain_openai import ChatOpenAI
from app.core.config import settings


def describe_product(image_base64: str) -> str:
    """把商品图片识别成文字描述，返回识别结果"""
    llm = ChatOpenAI(
        model="qwen3-vl-plus",      # ✅ 更快更便宜,
        base_url=settings.DASHSCOPE_BASE_URL,
        api_key=settings.DASHSCOPE_API_KEY,
        max_tokens=100,             # 🔴 限死输出长度，加快识图
    )

    resp = llm.invoke([
        {"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            {"type": "text",
             "text": ("识别图中商品，严格按这一行输出，逗号分隔，共5项，不超过60字，别写别的："
                      "品牌,名称,类别,3个关键属性")},
        ]}
    ])
    usage = getattr(resp,"usage_metadata",None) or {}

    return resp.content, usage.get("input_tokens",0), usage.get("output_tokens",0)
def pdf_image_to_text(image_base64: str, is_full_page: bool = False) -> str:
    """把 PDF 里抠出来的图（截图/图表/整页扫描）转成可检索文字"""
    llm = ChatOpenAI(
        model="qwen3-vl-plus",
        base_url=settings.DASHSCOPE_BASE_URL,
        api_key=settings.DASHSCOPE_API_KEY,
        max_tokens=2000,
        temperature=0.0,
    )
    kind = "这一页是扫描的整页文档" if is_full_page else "这是文档里的一张图（截图/图表/表格图片）"
    prompt = (
        f"{kind}。请把图里出现的文字和表格内容完整转成可检索的文本，"
        "表格用 Markdown 表格保留行列关系，保留所有数字和关键词，"
        "只输出内容本身，不要解释、不要客套。"
    )
    resp = llm.invoke([
        {"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
            {"type": "text", "text": prompt},
        ]}
    ])
    return (resp.content or "").strip()