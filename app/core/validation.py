"""
文件校验模块
"""

from fastapi import HTTPException, UploadFile
import os


# ============================================================
# 配置常量
# ============================================================

# 最大文件大小：10MB（字节）
MAX_FILE_SIZE = 10 * 1024 * 1024

# 允许的文件扩展名（白名单）
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".docx",
    ".xlsx", ".xls", ".html", ".htm",
    ".pptx", ".ppt", ".json", ".csv"
}
async def validate_file(file: UploadFile) -> None:
    """
    校验上传文件
    - 文件扩展名必须在白名单内
    - 文件大小 ≤ 10MB
    - 文件不能为空
    """
    # 1. 校验文件扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式:{file.filename},仅支持:{', '.join(ALLOWED_EXTENSIONS)}"
        )

    # 2. 校验文件大小
    content = await file.read()
    await file.seek(0)  # ⚠️ 重置指针，否则后续读取不到数据

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大,最大支持 10MB,当前文件大小为 {len(content) / 1024 / 1024:.2f}MB"
        )

    # 3. 校验文件是否为空
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")


