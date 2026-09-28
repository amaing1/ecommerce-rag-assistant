"""
PDF 结构化解析器：
把 PDF 逐页拆成「正文 / 表格 / 图片」三类，分别转成可入库的文本。

解决三个问题：
  1. 表格列关系被 pypdf 打散   -> pdfplumber 抽二维结构 -> 转 Markdown 表格
  2. 截图/图片被丢弃           -> PyMuPDF 抠图 -> qwen3-vl 转文字描述
  3. 乱码                     -> 换掉 pypdf，改走 pdfminer 引擎(pdfplumber 底层)

上下文保留（防“块孤岛”）：
  表格块不是光秃秃的表格，而是「章节标题 + 表格上方说明 + 表格」打包成一块，
  这样每个块拎出来都能独立看懂，检索到谁的注释都不会丢。

对外只暴露一个入口：parse_pdf(pdf_path) -> List[Document]
"""
import base64
import re
from typing import List

import fitz            # PyMuPDF
import pdfplumber
from langchain_core.documents import Document

from app.services.vision_service import pdf_image_to_text

# 是否把「无文字层的整页」当扫描件，渲染整页喂 VL 模型（按页计费）。默认关。
ENABLE_SCANNED_PAGE = False

# 常见中文标题开头：一、 二、 1. （一） 第1章 ……
_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十0-9]+[章节]|[一二三四五六七八九十]+[、.．]|[0-9]+[.、]|[（(][一二三四五六七八九十0-9]+[)）])"
)


def table_to_markdown(table: list) -> str:
    """把 pdfplumber 抽出的二维列表转成 Markdown 表格。"""
    if not table:
        return ""
    header = [str(c).replace("\n", " ").strip() if c is not None else "" for c in table[0]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in table[1:]:
        cells = [str(c).replace("\n", " ").strip() if c is not None else "" for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _is_heading(line: str) -> bool:
    """判断这一行是不是「章节标题」。"""
    return bool(_HEADING_RE.match(line.strip()))


def _words_to_lines(words):
    """把带坐标的词按「同一行高度」聚成若干行，返回 [(top, text)]，按 top 升序。"""
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    cur_line, cur_top = [], None
    for w in words:
        if cur_top is None or abs(w["top"] - cur_top) > 3:
            if cur_line:
                lines.append((cur_top, " ".join(t["text"] for t in cur_line)))
            cur_line, cur_top = [w], w["top"]
        else:
            cur_line.append(w)
    if cur_line:
        lines.append((cur_top, " ".join(t["text"] for t in cur_line)))
    return lines


def _collect_page_elements(page):
    """把一页的内容按「从上到下」排成一串元素（text 或 table），每个元素带 top 和 text。"""
    elements = []
    table_bboxes = []

    for t in page.find_tables():
        md = table_to_markdown(t.extract())
        if md.strip():
            elements.append({"kind": "table", "top": t.bbox[1], "text": md})
        table_bboxes.append(t.bbox)

    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    text_words = []
    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if not any(x0 <= cx <= x1 and top <= cy <= bottom
                   for x0, top, x1, bottom in table_bboxes):
            text_words.append(w)

    for top, text in _words_to_lines(text_words):
        elements.append({"kind": "text", "top": top, "text": text})

    elements.sort(key=lambda e: e["top"])
    return elements


def _extract_images(pdf_path: str) -> List[Document]:
    """用 PyMuPDF 抠出内嵌图，交给 qwen3-vl 转文字。"""
    docs: List[Document] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return docs
    for pno, page in enumerate(doc, start=1):
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:          # CMYK 等 4 通道 -> 转 RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                png = pix.tobytes("png")
            except Exception:
                continue
            try:
                desc = pdf_image_to_text(base64.b64encode(png).decode())
            except Exception:
                continue
            if desc:
                docs.append(Document(
                    page_content=desc,
                    metadata={"page": pno, "chunk_type": "image"},
                ))
    doc.close()
    return docs


def _scanned_pages(pdf_path: str, page_numbers: List[int]) -> List[Document]:
    """整页渲染成图喂 VL（给扫描件用，按页计费）。"""
    docs: List[Document] = []
    if not page_numbers:
        return docs
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return docs
    for pno in page_numbers:
        try:
            pix = doc[pno - 1].get_pixmap(dpi=150)
            png = pix.tobytes("png")
            desc = pdf_image_to_text(base64.b64encode(png).decode(), is_full_page=True)
            if desc:
                docs.append(Document(page_content=desc,
                                     metadata={"page": pno, "chunk_type": "image"}))
        except Exception:
            continue
    doc.close()
    return docs


def parse_pdf(pdf_path: str) -> List[Document]:
    """PDF 结构化解析入口。"""
    docs: List[Document] = []
    current_heading = ""         # 跨页记住当前章节标题
    content_pages = set()

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            elements = _collect_page_elements(page)
            body_lines = []      # 连续的正文行
            caption = ""         # 表格上方最近的一行正文

            for el in elements:
                if el["kind"] == "text":
                    line = el["text"].strip()
                    if not line:
                        continue
                    if _is_heading(line):
                        current_heading = line
                    body_lines.append(line)
                    caption = line
                else:  # table
                    # 表格前的正文先成块
                    if body_lines:
                        docs.append(Document(
                            page_content="\n".join(body_lines),
                            metadata={"page": pno, "chunk_type": "text"},
                        ))
                        content_pages.add(pno)
                        body_lines = []
                    # 表格块 = 章节标题 + 表格说明 + 表格（自包含）
                    parts = []
                    if current_heading and current_heading != caption:
                        parts.append(current_heading)
                    if caption:
                        parts.append("表格说明：" + caption)
                    parts.append(el["text"])
                    docs.append(Document(
                        page_content="\n".join(parts),
                        metadata={"page": pno, "chunk_type": "table"},
                    ))
                    content_pages.add(pno)
                    caption = ""

            # 页尾剩余正文成块
            if body_lines:
                docs.append(Document(
                    page_content="\n".join(body_lines),
                    metadata={"page": pno, "chunk_type": "text"},
                ))
                content_pages.add(pno)

    # 图片单独抠出来描述
    docs.extend(_extract_images(pdf_path))
    for d in docs:
        content_pages.add(d.metadata.get("page"))

    if ENABLE_SCANNED_PAGE:
        scanned = [p for p in range(1, total_pages + 1) if p not in content_pages]
        docs.extend(_scanned_pages(pdf_path, scanned))

    return docs