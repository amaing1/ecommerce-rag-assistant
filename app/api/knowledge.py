"""
知识库上传接口：支持多格式文件上传，自动解析、清洗、分块、建索引

功能：用户通过 HTTP 上传文档，系统自动完成：
    1. 文件格式校验（白名单机制）
    2. 读取文件内容
    3. 调用 DocumentLoader 解析、清洗、分块
    4. 调用 RAGService 构建向量索引 + BM25 索引
    5. 返回文档 ID 和分块数量

依赖：
    - DocumentLoader：解析多格式文件
    - RAGService：构建索引（复用 chat 接口的实例）
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid
from pydantic import BaseModel
from typing import List, Optional
from app.services.document_loader import DocumentLoader
from app.services.rag_service import RAGService
from app.core.logger import logger
from app.api.deps import get_current_user
from app.models import User, Document as DocumentModel, KnowledgeBase
from fastapi import Depends
from app.core.validation import validate_file
from app.database import get_db
from sqlalchemy.orm import Session
import requests
from app.core.config import settings

# 创建路由实例（用于注册到 FastAPI）
router = APIRouter()

# 创建 RAG 服务实例（单例，与 chat.py 共享同一个实例）
# 这样上传的文件可以被 chat 接口检索到
rag = RAGService()

# ---------- 请求/响应模型 ----------
class QueryRequest(BaseModel):
    """知识库查询请求"""
    question: str
    top_k: Optional[int] = 5
    mode: Optional[str] = "混合检索"


class QueryResult(BaseModel):
    """单条查询结果"""
    content: str
    score: float


class QueryResponse(BaseModel):
    """知识库查询响应"""
    results: List[QueryResult]
    total: int


@router.post("/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...),current_user: User = Depends(get_current_user),db: Session = Depends(get_db)):
    """
    上传知识库文档接口

    请求方式：POST
    请求体：multipart/form-data，包含一个文件字段

    支持的文件格式：
        .pdf, .txt, .md, .docx, .xlsx, .xls,
        .html, .htm, .pptx, .ppt, .json, .csv

    返回：
        doc_id: str       文档唯一标识
        filename: str     原始文件名
        chunk_count: int  分块数量
        message: str      状态信息

    异常情况：
        - 不支持的格式 → 400 Bad Request
        - 文件为空 → 400 Bad Request
        - 解析后无有效内容 → 400 Bad Request
        - 处理过程中异常 → 500 Internal Server Error
    """
    # ================================================================
    # 第1步：校验文件扩展名（白名单机制）
    # ================================================================

    # 定义允许上传的格式列表
    allowed_extensions = [
        ".pdf", ".txt", ".md", ".docx",
        ".xlsx", ".xls", ".html", ".htm",
        ".pptx", ".ppt", ".json", ".csv"
    ]

    # 初始化匹配标记（None 表示尚未匹配到）
    ext = None

    # 遍历白名单，检查文件名是否以某个后缀结尾
    for allowed in allowed_extensions:
        if file.filename.lower().endswith(allowed):
            ext = allowed          # 匹配成功，记录后缀
            break                  # 退出循环（不需要继续检查）

    # 如果循环结束后 ext 仍然是 None，说明格式不在白名单中
    if ext is None:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {file.filename}，仅支持: {', '.join(allowed_extensions)}"
        )

    # ================================================================
    # 1.5步:判断文件大小是否合适
    await validate_file(file)
    # 第2步：读取文件内容
    # ================================================================

    # await file.read() 异步读取上传文件的全部内容，返回 bytes
    content = await file.read()

    # 检查文件是否为空
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    # ================= 新增 : 服务端去重检查(基于数据库) ===============
    doc_key = f"{file.filename}_{len(content)}"
    # Document 表没有 user_id，需要通过 KnowledgeBase 关联查询
    existing_doc = db.query(DocumentModel).join(KnowledgeBase).filter(
        DocumentModel.filename == file.filename,
        KnowledgeBase.user_id == current_user.id
    ).first()
    if existing_doc:
        raise HTTPException(
            status_code=400,
            detail=f"文件'{file.filename}'已存在，请勿重复上传"
        )

    # ================================================================
    # 第3步：解析 + 清洗 + 分块
    # ================================================================

    try:
        # 调用 DocumentLoader 处理文件
        # 返回：List[Document]，每个 Document 包含 page_content 和 metadata
        chunks = DocumentLoader.load_and_split(content, file.filename)
        # ========== 新增：入库前 metadata 消毒 ==========
        # Chroma 只接受 str / int / float / bool / None，
        # 其他类型（list / dict / tuple / set）一律转成字符串
        for i, chunk in enumerate(chunks):
            clean = {}
            for k, v in (chunk.metadata or {}).items():
                if isinstance(v, (list, tuple, set)):
                    logger.warning(
                        f"[BAD-META] idx={i} key={k} type={type(v).__name__} "
                        f"value={v} —— 已转字符串"
                    )
                    clean[k] = ", ".join(str(x) for x in v)
                elif isinstance(v, dict):
                    clean[k] = str(v)
                elif v is None or isinstance(v, (str, int, float, bool)):
                    clean[k] = v
                else:
                    clean[k] = str(v)
            chunk.metadata = clean
        # ================================================

        # 如果 chunks 为空列表，说明解析后没有任何有效内容
        if not chunks:
            raise HTTPException(status_code=400, detail="文档解析后没有有效内容")
        # =========== 新增 ：给每个块注入去重键元组
        for chunk in chunks:
            chunk.metadata["doc_key"] = doc_key

        # ================================================================
        # 第4步：构建索引（存入知识库）
        # ================================================================

        # rag.load_knowledge_base() 内部会调用：
        #   1. vector_db.add_documents(chunks) → 存入 Chroma 向量库
        #   2. BM25Okapi(corpus) → 构建 BM25 关键词索引
        rag.load_knowledge_base(chunks)

        # ================================================================
        # 第5步：生成文档 ID + 保存到数据库 + 记录日志 + 返回结果
        # ================================================================

        # 生成全局唯一标识符（UUID），用于追踪这份文档
        doc_id = str(uuid.uuid4())

        # 查找或创建用户的默认知识库
        default_kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.user_id == current_user.id
        ).first()
        if not default_kb:
            default_kb = KnowledgeBase(
                name="默认知识库",
                description="自动创建的默认知识库",
                user_id=current_user.id
            )
            db.add(default_kb)
            db.commit()
            db.refresh(default_kb)

        # 保存文档记录到数据库（用于去重检查）
        new_doc = DocumentModel(
            doc_id=doc_id,
            filename=file.filename,
            file_type=ext,
            file_size=len(content),
            knowledge_base_id=default_kb.id
        )
        db.add(new_doc)
        db.commit()

        # 记录成功日志（方便排查问题）
        logger.info(f"知识库上传成功: {file.filename}, 分块数: {len(chunks)}, ID: {doc_id}")

        # 返回结果给调用方
        return {
            "doc_id": doc_id,
            "filename": file.filename,
            "chunk_count": len(chunks),   # 前端需要展示分块数量
            "message": "知识库上传成功"
        }

    # ================================================================
    # 第6步：异常捕获（兜底处理）
    # ================================================================

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("=" * 70)
        print("[FATAL] 知识库上传失败:")
        print(tb)
        print("=" * 70)
        logger.error(f"知识库上传失败: {str(e)}\\n{tb}")
        raise HTTPException(status_code=500, detail=f"处理文档时出错: {str(e)}")



# ================================================================
# 今天遇到的错误及解决方法（踩坑记录）
# ================================================================

"""
【问题1】python-multipart 未安装
    报错：RuntimeError: Form data requires "python-multipart" to be installed.
    原因：FastAPI 处理文件上传（multipart/form-data）需要此包。
    解决：pip install python-multipart -i https://pypi.tuna.tsinghua.edu.cn/simple

【问题2】unstructured 未安装
    报错：unstructured package not found, please install it with `pip install unstructured`
    原因：document_loader.py 中使用了 UnstructuredMarkdownLoader 等 Loader，依赖 unstructured。
    解决：pip install unstructured -i https://pypi.tuna.tsinghua.edu.cn/simple

【问题3】markdown 未安装
    报错：No module named 'markdown'
    原因：unstructured 在解析 .md 文件时需要 markdown 包，但未自动安装。
    解决：pip install markdown -i https://pypi.tuna.tsinghua.edu.cn/simple

【问题4】knowledge.py 缩进错误导致格式校验失败
    现象：上传 .txt 文件仍然报"不支持的文件格式"
    错误代码：if ext is None 被放在了 for 循环内部
    原因：第一次循环检查 .pdf 不匹配就立即抛出异常，根本没机会检查 .txt
    解决：将 if ext is None 移到 for 循环**外面**

【问题5】File() 缺少 ...
    错误代码：file: UploadFile = File()
    报错：再次提示 python-multipart 缺失
    原因：File() 缺少 ... 会导致 FastAPI 路由解析异常
    正确写法：file: UploadFile = File(...)

【问题6】依赖清单
    需添加到 requirements.txt 的包：
        python-multipart==0.0.20
        unstructured==0.18.3
        markdown==3.6
    安装命令：
        pip install python-multipart unstructured markdown -i https://pypi.tuna.tsinghua.edu.cn/simple
"""


# ================================================================
# 第2块：查询接口函数
# ================================================================

@router.post("/knowledge/query", response_model=QueryResponse)
async def query_knowledge(request: QueryRequest,current_user: User = Depends(get_current_user)):
    """
    知识库查询接口：输入问题，返回最相关的文档片段及相似度分数
    使用混合检索（BM25 + 向量 + Reranker）+ 阈值过滤
    """


    # 1. 调用混合检索（BM25 + 向量 + Reranker，已去重和重排）或者BM25检索
    if request.mode == "纯BM25检索":
        docs = rag.retriever.bm25_only(request.question,top_k=request.top_k)
    else:
        docs = rag.retriever.hybrid_query(request.question)


    # 2. 如果没有结果，直接返回空
    if not docs:
        return QueryResponse(results=[], total=0)

    # 3. 调用百炼API精排
    url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    headers = {
        "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "qwen3-rerank",
        "input":{
            "query": request.question,
            "documents": [d.page_content for d in docs],
        },
        "parameters": {"top_n":request.top_k},
    }
    resp = requests.post(url,json=payload,headers=headers,timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("output",{}).get("results",[]):
        idx = item.get("index")
        score = item.get("relevance_score",0.0)
        if idx is not None and idx < len(docs):
            results.append(QueryResult(
                content=docs[idx].page_content,
                score=round(float(score),4)
            ))
    return QueryResponse(results=results,total=len(results))



"""
今天遇到的错误及解决方法：

【问题1】/knowledge/query 返回了旧数据（知识库残留）
    现象：
        - 上传《30秒Demo制作脚本_那盏灯.md》后，查询时返回了"60天计划"的内容
        - 明明只上传了一份文档，却查到了多份文档的内容

    原因：
        - 之前测试时多次上传过不同文件，数据残留在 Chroma 中
        - 手动删除 vector_store/ 文件夹时，因文件占用未成功删除
        - /knowledge/clear 接口因参数类型错误报错，未真正清空

    解决：
        - 重启电脑（释放所有文件占用）
        - 删除 vector_store/ 文件夹（彻底清空物理文件）
        - 重启服务，只上传《30秒Demo制作脚本_那盏灯.md》
        - 再次查询时只返回脚本内容

【问题2】/knowledge/clear 接口报错
    报错：
        pysqlite3.dbapi2.InterfaceError: Error binding parameter 0 - probably unsupported type.

    原因：
        - delete_collection 接收的 collection_name 参数类型有误
        - 可能是 list 或 tuple，不是字符串

    解决：
        - 在删除时使用 str(collection) 强制转换为字符串
        - 修改后接口正常工作

【问题3】vector_store/ 文件夹无法删除
    现象：
        - 右键删除时提示"文件正在使用"

    原因：
        - uvicorn 服务正在运行，锁定了 SQLite 数据库文件
        - 或 PyCharm 的终端窗口未完全关闭

    解决：
        - 按 Ctrl+C 停掉服务
        - 关闭所有 PyCharm 终端标签页
        - 如果仍无法删除，重启电脑（最彻底的方式）

【总结】知识库管理的两种方式：
    方式一：手动删除 vector_store/ 文件夹（物理删除，100% 干净）
    方式二：调用 /knowledge/clear 接口（程序删除，更便捷）

    建议：
        - 开发测试阶段，用 /knowledge/clear 接口清空
        - 如果接口报错，用手动删除文件夹兜底
        - 生产环境建议禁用 /knowledge/clear，或用权限控制
"""
