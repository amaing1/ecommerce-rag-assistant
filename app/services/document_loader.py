"""
文档加载器：支持多格式文档的读取、清洗、分块
覆盖电商知识库常见格式：PDF、TXT、MD、DOCX、XLSX、HTML、JSON、CSV、PPTX

功能流程：读取文件 → 清洗文本 → 分块 → 返回 Document 列表
"""

import os
import re
import tempfile
import json
import csv
from typing import List

# LangChain 文档加载器（支持各种格式）
from langchain_community.document_loaders import (
    PyPDFLoader, #PDF
    UnstructuredMarkdownLoader, #markdown
    Docx2txtLoader,  #docs
    TextLoader,  # TXT
    UnstructuredExcelLoader,  # XLSX / XLS
    UnstructuredHTMLLoader,  # HTML / HTM
    UnstructuredPowerPointLoader,  # PPTX / PPT
)
from langchain_text_splitters import (RecursiveCharacterTextSplitter,MarkdownHeaderTextSplitter)
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings
from app.core.config import settings
from langchain_core.documents import Document

class DocumentLoader:
    """
    统一文档加载器：读取 → 清洗 → 分块

    所有方法都是静态方法（@staticmethod），因为：
    - 不需要访问实例属性（没有 self.xxx）
    - 所有数据都通过参数传入
    - 可以直接通过类名调用：DocumentLoader.load_and_split()
    """

    # ============================================================
    # 第2块：支持格式映射表
    # ============================================================

    # 把文件扩展名和对应的 LangChain Loader 类绑定
    # 新增格式只需要在这里加一行，主逻辑不用改
    SUPPORTED_LOADERS = {
        ".pdf": PyPDFLoader,
        ".txt": TextLoader,
        ".md": UnstructuredMarkdownLoader,
        ".docx": Docx2txtLoader,
        ".xlsx": UnstructuredExcelLoader,
        ".xls": UnstructuredExcelLoader,
        ".html": UnstructuredHTMLLoader,
        ".htm": UnstructuredHTMLLoader,
        ".pptx": UnstructuredPowerPointLoader,
        ".ppt": UnstructuredPowerPointLoader,
    }

    #噪音提示词
    NOISE_WORDS = [
        "敬请期待", "到货通知", "喜欢", "价格说明",
        "预约维修服务", "官方微信", "选购指南", "商品详情",
    ]

    # 特殊处理：JSON 和 CSV 不用 LangChain Loader，而是自己解析
    # 原因：LangChain 的默认 Loader 会把整行拼接成一个字符串，
    #       丢失了“列名”信息，导致检索效果变差
    SPECIAL_HANDLERS = {".json", ".csv"}
    ####嵌入模型缓存（云 embedding：走 DashScope 兼容接口，绕开 dashscope SDK）
    _embeddings = None

    @classmethod
    def get_embeddings(cls):
        if cls._embeddings is None:
            cls._embeddings = OpenAIEmbeddings(
                model="text-embedding-v1",
                openai_api_key=settings.DASHSCOPE_API_KEY,
                openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        return cls._embeddings


    # ============================================================
    # 第3块：辅助方法
    # ============================================================

    @staticmethod
    def _get_loader_class(ext: str):
        """
        根据扩展名从 SUPPORTED_LOADERS 字典里查找对应的 Loader 类
        如果找不到，抛出异常
        """
        loader_class = DocumentLoader.SUPPORTED_LOADERS.get(ext)
        if loader_class is None:
            raise ValueError(f"不支持的文件格式: {ext}，支持: {list(DocumentLoader.SUPPORTED_LOADERS.keys())}")
        return loader_class

    @staticmethod
    def _clean_docs(docs: List[Document],compress_newlines:bool = True) -> List[Document]:
        """
        清洗文档内容：
        - 多个换行压缩成单个换行
        - 多个空格压缩成单个空格
        - 去除页码标记（第X页 / PX / Page X）
        - 去除特殊装饰符号
        - 过滤掉空文档
        """
        cleaned = []
        for doc in docs:
            text = doc.page_content
            if compress_newlines:
                # 多个换行压缩成单个换行
                text = re.sub(r"\n+", "\n", text)
            if compress_newlines:
                # 多个空格压缩成单个空格
                text = re.sub(r"\s+", " ", text)
            else:
                #[^\S\n]+ 的意思是：压缩空格和制表符，但不动换行符。
                text = re.sub(r"[^\S\n]+", " ", text)

            # 去除页码标记（第X页 / PX / Page X）
            text = re.sub(r"第\d+页|P\d+|Page\s*\d+", "", text, flags=re.IGNORECASE)
            # 去除特殊装饰符号（保留 # ，因为 Markdown 标题需要用）
            text = re.sub(r"[※@￥%&★◆■]", "", text)
            # 不删 URL —— 它是购买链接，用户可能会问！
            # 只做两件事：① 把"来源："改成"购买链接："   ② 去掉追踪参数 &cfrom=search
            text = re.sub(r"来源[:：]\s*(https?://\S+)", r"购买链接：\1", text)
            text = text.replace("&cfrom=search", "")
            # 删除网页图标的乱码字符（PUA）
            text = re.sub(r"[\ue000-\uf8ff]", "", text)
            # 删除导航噪音词
            for w in DocumentLoader.NOISE_WORDS:
                text = text.replace(w, "")
            # 去除首尾空白
            text = text.strip()
            # 过滤空文档（内容为空的直接丢弃）
            if len(text) > 0:
                doc.page_content = text
                cleaned.append(doc)
        return cleaned

    # ============================================================
    # 第4块：JSON / CSV 自定义解析器
    # ============================================================

    @staticmethod
    def _parse_json(file_path: str, filename: str) -> List[Document]:
        """
        解析 JSON 文件，支持数组格式和对象格式

        为什么不直接用 JSONLoader？
        - JSONLoader 需要写 .jq 查询语法，学习成本高
        - 自己解析可以控制输出格式，直接提取 content/text/answer 等字段
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        docs = []
        # 如果 JSON 是数组，遍历每一项
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    # 尝试提取常见字段：content、text、answer、question
                    content = (
                            item.get("content") or
                            item.get("text") or
                            item.get("answer") or
                            (item.get("question", "") + " " + item.get("answer", "") if "question" in item else "")
                    )
                    # 如果都没匹配到，把整个对象转成 JSON 字符串
                    if not content:
                        content = json.dumps(item, ensure_ascii=False)
                else:
                    content = str(item)
                doc = Document(page_content=content, metadata={"source": filename, "index": idx})
                docs.append(doc)
        # 如果 JSON 是对象，把值拼接成文本
        elif isinstance(data, dict):
            content = "\n".join([f"{k}: {v}" for k, v in data.items() if isinstance(v, str)])
            docs.append(Document(page_content=content, metadata={"source": filename}))

        return docs

    @staticmethod
    def _parse_csv(file_path: str, filename: str) -> List[Document]:
        """
        解析 CSV 文件：每行作为一个 Document

        为什么不直接用 CSVLoader？
        - CSVLoader 会把整行拼接成 "列1值 列2值 列3值"
        - 我们自己解析成 "列名: 值" 的格式，保留列名信息
        - 这样用户问 "退货政策" 时，系统可以匹配到 "question: 怎么退货" 这一列
        """
        docs = []
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for idx, row in enumerate(reader):
                # 将每行转为 "列名: 值" 的文本，用空格连接
                content = " ".join([f"{col}: {row.get(col, '')}" for col in headers if row.get(col)])
                if content.strip():
                    doc = Document(page_content=content, metadata={"source": filename, "row": idx})
                    docs.append(doc)
        return docs

    # ============================================================
    # 第5块：分块器配置
    # ============================================================

    # ============================================================
    # 第5块：按文件类型分区的分块器配置
    # ============================================================

    # 不同文件类型的分块参数
    # 原因：PDF/DOCX 是长文档，需要大块保留上下文；
    #       CSV/JSON 本身已经是结构化小条目，不需要再切或只切一刀；
    #       TXT/MD 视内容密度取中间值
    CHUNK_CONFIGS = {
        # 长文档类：自然段落结构，大块保留完整语义
        ".pdf":  {"chunk_size": 1000, "chunk_overlap": 100},
        ".docx": {"chunk_size": 1000, "chunk_overlap": 100},
        ".pptx": {"chunk_size": 800,  "chunk_overlap": 80},
        ".ppt":  {"chunk_size": 800,  "chunk_overlap": 80},
        # 纯文本类：内容密度不一，取中间值
        # .txt 大块原因：知识库 txt 先按"商品名称："拆块，每个商品一块（多数 <2000 字符）
        #   用 2000 字符切分能让绝大多数商品保持"一个商品一个分块"（商品名+参数不分离），
        #   只有超长商品（>2000字符）才会被切，且商品名和开头参数仍在第一块。
        ".txt":  {"chunk_size": 2000, "chunk_overlap": 200},
        ".md":   {"chunk_size": 600,  "chunk_overlap": 60},
        ".html": {"chunk_size": 600,  "chunk_overlap": 60},
        ".htm":  {"chunk_size": 600,  "chunk_overlap": 60},
        # 结构化数据类：每条记录已经很短，小块或不切
        ".json": {"chunk_size": 200,  "chunk_overlap": 20},
        ".csv":  {"chunk_size": 200,  "chunk_overlap": 20},
        ".xlsx": {"chunk_size": 200,  "chunk_overlap": 20},
        ".xls":  {"chunk_size": 200,  "chunk_overlap": 20},
    }

    # 默认参数（兜底，万一扩展名不在上面的表里）
    DEFAULT_CHUNK = {"chunk_size": 600, "chunk_overlap": 60}

    @staticmethod
    def _get_splitter(ext: str = "") -> RecursiveCharacterTextSplitter:
        """
        根据文件扩展名返回对应的分块器

        参数：
            ext: 文件扩展名（如 ".pdf"），用于选择分块参数

        为什么不统一用一套参数？
        - PDF/DOCX 通常是很长的文档，chunk_size=1000 能装下完整段落
        - CSV/JSON 每条记录本身就很短（50-200字），用大块会把多条记录混在一起
        - 统一参数要么太大会浪费 token，要么太小会切断上下文
        """
        config = DocumentLoader.CHUNK_CONFIGS.get(ext, DocumentLoader.DEFAULT_CHUNK)
        return RecursiveCharacterTextSplitter(
            chunk_size=config["chunk_size"],
            chunk_overlap=config["chunk_overlap"],
            separators=["\n\n", "\n", "。", "？", "！", "；", "，", " ", ""],
            length_function=len,
        )
    @staticmethod
    def _split_by_product_name(docs, marker="商品名称："):
        """
               把文档按"商品名称："边界拆成商品块。
               返回新的 Document 列表，每个商品一块（保留原文，不截断）。
               """
        from langchain_core.documents import Document
        new_docs = []
        for doc in docs:
            text = doc.page_content
            # 按 marker 切分，保留 marker（"商品名称："开头）
            parts = []
            start = 0
            while True:
                idx = text.find(marker,start)
                if idx == -1:
                    # 最后一段(marker之后的内容)
                    if start < len(text):
                        parts.append(text[start:])
                    break
                if idx > start:
                    parts.append(text[start:idx])
                # 找下一个 marker，确定本商品块的结束
                next_idx = text.find(marker, idx + len(marker))
                end = next_idx if next_idx != -1 else len(text)
                parts.append(text[idx:end])
                start = end
            # 每一个part生成一个Document
            for p in parts:
                if p.strip():
                    new_docs.append(Document(page_content=p,metadata=doc.metadata))
        return new_docs




    # 清洗指令：告诉 LLM 怎么判断、输出什么格式
    CLEAN_PROMPT = """你是知识库数据清洗助手。下面有 {n} 段从电商网页抓取的文字，每段放在编号标签里。

请逐段判断：这段文字是否包含【有用的商品或服务信息】（如商品名称、价格、参数、售后政策、发货说明等）。

只输出需要【丢弃】的段编号，多个编号用英文逗号分隔（例如 0,3,7）。
如果所有段落都有用，只输出 NONE。

判断原则：只有明确是"网页导航碎片、按钮文字、无意义乱码"时才丢弃；
凡是包含商品名、价格、参数、政策等字样的，或是拿不准的，一律保留。
除此之外不要输出任何内容。

待判断的段落：
{chunks}"""

    # 【块2】缓存变量 + 造清洗工具（只造一次）
    _clean_llm = None

    @classmethod
    def get_llm(cls):
        """惰性初始化清洗用大模型（清洗是轻任务，用 ROUTER 模型）"""
        if cls._clean_llm is None:
            from langchain_openai import ChatOpenAI
            cls._clean_llm = ChatOpenAI(
                model=settings.DASHSCOPE_MODEL_ROUTER,
                base_url=settings.DASHSCOPE_BASE_URL,
                api_key=settings.DASHSCOPE_API_KEY,
                temperature=0.0,
            )
        return cls._clean_llm

    # 【块3】翻译官：把 LLM 的回答翻译成程序能懂的编号
    @staticmethod
    def _parse_skip_ids(text: str, n: int):
        """把 LLM 返回的 '0,3,7' 或 'NONE' 解析成要丢弃的编号集合"""
        text = text.strip()
        if not text or text.upper() == "NONE":
            return set()
        ids = set()
        for part in text.replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
        return ids

    # 【块4】总调度：批处理 + 并发 + 丢垃圾
    @classmethod
    def _llm_clean_chunks(cls,docs,batch_size=15,max_workers=4):
        """LLM 深度清洗：批处理 + 并发，丢弃无意义的垃圾分块"""
        from concurrent.futures import ThreadPoolExecutor

        if not docs:
            return docs
        llm = cls.get_llm()
        # 第2板斧：批处理 —— 每 15 段装进一个请求
        batches = [docs[i:i + batch_size]for i in range(0,len(docs),batch_size)]
        ##clean_batch 把一批块，打包成"带编号的文本"，准备喂给 LLM
        def clean_batch(batch):
            chunks_txt = "\n".join(
                f"<{i}> {d.page_content} </{i}>" for i, d in enumerate(batch)
            )
            prompt = DocumentLoader.CLEAN_PROMPT.format(
                n=len(batch),chunks=chunks_txt
            )
            resp = llm.invoke(prompt)
            skip_ids = DocumentLoader._parse_skip_ids(resp.content,len(batch))
            return [d for i,d in enumerate(batch) if i not in skip_ids]
        # 第3板斧：并发 —— 用线程池同时发多个请求
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            kept_lists = list(pool.map(clean_batch,batches))
        # 合并所有保留下来的分块
        return [d for sub in kept_lists for d in sub]



    # ============================================================
    # 第6块：主入口方法（调用方唯一需要接触的方法）
    # ============================================================

    @staticmethod
    def load_and_split(file_content: bytes, filename: str) -> List[Document]:
        """
        加载并切分文档：根据扩展名自动选择解析器

        参数：
            file_content: 上传文件的二进制内容（bytes）
            filename: 上传文件的原始文件名

        返回：
            List[Document]: 清洗并分块后的文档列表

        完整执行路径：
            上传文件 → 判断格式 → 解析 → 清洗 → 分块 → 返回
        """

        # ---- 第6-1段：获取扩展名 ----
        # 从文件名中取出后缀（如 ".pdf"），转小写
        ext = os.path.splitext(filename)[1].lower()

        # ---- 第6-2段：Markdown 文件直接处理（跳过 Loader，保留 # 标题标记） ----
        if ext == ".md":
            # 直接读原始内容（不用 Loader，因为 Loader 会去掉 # 标题符号）
            raw_text = file_content.decode("utf-8")
            raw_doc = Document(page_content=raw_text)
            # 用 _clean_docs 清洗，compress_newlines=False 保留换行和标题标记
            cleaned = DocumentLoader._clean_docs([raw_doc], compress_newlines=False)
            if not cleaned:
                return []
            full_text = cleaned[0].page_content
            headers_to_split_on = [
                ("#", "Header1"),
                ("##", "Header2"),
                ("###", "Header3"),
            ]
            md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
            md_docs = md_splitter.split_text(full_text)
            for doc in md_docs:
                doc.metadata["source"] = filename
            md_docs = DocumentLoader._llm_clean_chunks(md_docs)
            return md_docs

        # ---- 第6-3至6-5段：特殊格式（JSON / CSV） ----
        # 如果文件是 JSON 或 CSV，走自定义解析分支
        if ext in DocumentLoader.SPECIAL_HANDLERS:
            # 写入临时文件（因为 _parse_json 和 _parse_csv 需要文件路径）
            with tempfile.NamedTemporaryFile(mode="wb", suffix=ext, delete=False) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name

            # 解析临时文件
            try:
                if ext == ".json":
                    raw_docs = DocumentLoader._parse_json(tmp_path, filename)
                elif ext == ".csv":
                    raw_docs = DocumentLoader._parse_csv(tmp_path, filename)
                else:
                    raw_docs = []
            finally:
                # 删除临时文件（解析完成，不再需要）
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # 清洗 + 分块 + 返回
            cleaned_docs = DocumentLoader._clean_docs(raw_docs)
            # CSV 已按「一行 = 一个商品」解析好，直接入库，不再二次切分
            # （否则 200 字切分会把「商品名」和「关键参数」切散，导致参数检索不准）
            if ext == ".csv":
                return DocumentLoader._llm_clean_chunks(cleaned_docs)
            # JSON 等其他结构化格式：仍按原有 chunk_size 切分
            splitter = DocumentLoader._get_splitter(ext)
            chunks = splitter.split_documents(cleaned_docs)
            return DocumentLoader._llm_clean_chunks(chunks)

        # ---- 第6-5.5段：PDF 走结构化解析（正文/表格/图片分开处理） ----
        if ext == ".pdf":
            from app.services.pdf_parser import parse_pdf
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            try:
                blocks = parse_pdf(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            if not blocks:
                return []

            # 正文用「按长度切块」，不依赖任何 embedding 模型（快、零云成本、不再报错）
            splitter = DocumentLoader._get_splitter(".pdf")

            final_docs: List[Document] = []
            for block in blocks:
                block.metadata["source"] = filename
                ctype = block.metadata.get("chunk_type", "text")
                if ctype == "text":
                    cleaned = DocumentLoader._clean_docs([block])
                    if not cleaned:
                        continue
                    for d in splitter.split_documents([cleaned[0]]):
                        d.metadata = {
                            "source": filename,
                            "chunk_type": "text",
                            "page": block.metadata.get("page"),
                        }
                        final_docs.append(d)
                else:
                    # 表格/图片：整块入库，不再切、不再清洗
                    final_docs.append(block)

            return final_docs



        # ---- 第6-6段：标准格式（PDF / TXT / DOCX / PPTX / HTML 等） ----
        # 从映射表获取对应的 Loader 类（比如 ".pdf" → PyPDFLoader）
        loader_class = DocumentLoader._get_loader_class(ext)

        # ---- 第6-7段：写入临时文件 ----
        # 为什么需要临时文件？
        # LangChain 的 Loader（PyPDFLoader、Docx2txtLoader 等）只接受文件路径，
        # 不接受内存中的 bytes。所以必须先把 bytes 写入临时文件，拿到路径。
        with tempfile.NamedTemporaryFile(mode="wb", suffix=ext, delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name

        # ---- 第6-8段：实例化 Loader + 读取文档 ----
        try:
            # 纯文本文件（.txt）需要指定编码，否则可能乱码
            # 其他格式（PDF、DOCX 等）自带编码信息，不需要指定
            if ext == ".txt":
                loader = loader_class(tmp_path, encoding="utf-8")
            else:
                loader = loader_class(tmp_path)

            # 调用 LangChain Loader 读取文档内容，返回 Document 列表
            raw_docs = loader.load()
        finally:
            # 删除临时文件（无论加载成功还是失败，都会执行）
            # 因为内容已经读到 raw_docs 里了，临时文件不再需要
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        # ---- 第6-9段：添加来源信息（文件名） ----
        # LangChain Loader 不会自动添加文件名，
        # 所以需要手动给每个 Document 加上 source 元数据
        # 作用：用户问"这个答案从哪来的？"时可以回答
        for doc in raw_docs:
            doc.metadata["source"] = filename

        # ---- 第6-10段：清洗 + 分块 + 返回 ----
        # ========== 修改后的分块逻辑（支持按文件类型选择不同策略） ==========

        # ---- 第6-11段：根据扩展名选择分块策略 ----
        # 策略2：PDF / DOCX / PPTX 使用语义切分
        if ext in [".pdf", ".docx", ".pptx", ".ppt"]:
            # 先清洗文档
            cleaned_docs = DocumentLoader._clean_docs(raw_docs)
            if not cleaned_docs:
                return []
            # 获取千问嵌入模型（第一次调用时会初始化）
            embeddings = DocumentLoader.get_embeddings()
            # 创建语义切分器
            # breakpoint_threshold_type="percentile"：使用百分位数判断切分点
            # breakpoint_threshold_amount=95：百分位阈值，值越大切分越粗（块越大）
            semantic_splitter = SemanticChunker(
                embeddings=embeddings,
                breakpoint_threshold_type="percentile",
                breakpoint_threshold_amount=95,
            )
            # 将所有文档内容合并成一个完整文本
            full_text = "\n".join([doc.page_content for doc in cleaned_docs])
            # 执行语义切分，返回 Document 列表
            semantic_docs = semantic_splitter.create_documents([full_text])
            # 为每个块添加来源文件名
            for doc in semantic_docs:
                doc.metadata["source"] = filename
            # 返回语义切分后的文档块
            semantic_docs = DocumentLoader._llm_clean_chunks(semantic_docs)
            return semantic_docs

        # 策略3：其他格式（.txt, .html 等）使用原来的长度切分
        else:
            # 先清洗文档
            cleaned_docs = DocumentLoader._clean_docs(raw_docs)
            if not cleaned_docs:
                return []
            # 使用原有的 _get_splitter 方法，根据扩展名选择 chunk_size
            splitter = DocumentLoader._get_splitter(ext)
            # ======新增: txt 先按"商品名称："拆成商品块,避免商品名和参数被切散"
            if ext == ".txt":
                cleaned_docs = DocumentLoader._split_by_product_name(cleaned_docs)
            # 执行长度切分
            chunks = splitter.split_documents(cleaned_docs)
            # 返回切分后的文档块
            chunks = DocumentLoader._llm_clean_chunks(chunks)    #最后在调用大模型清洗一下
            return chunks






