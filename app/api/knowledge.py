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
