from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.services.system import get_health

router = APIRouter(prefix="/api", tags=["系统状态"])


@router.get("/health")
def health():
    data, status_code = get_health()
    return JSONResponse(status_code=status_code, content={"code": "OK" if status_code == 200 else "DATABASE_UNAVAILABLE", "message": "基础服务可用" if status_code == 200 else "数据库暂不可用", "data": data})
