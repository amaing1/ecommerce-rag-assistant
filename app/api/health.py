from fastapi import APIRouter   # 必须导入

router = APIRouter()            # 必须创建实例

@router.get("/")
async def root():
    return {"message": "电商售后知识库智能问答助手 已启动"}

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "rag-assistant"}

