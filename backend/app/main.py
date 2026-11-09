from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.controllers.system import router
from backend.app.controllers.auth import router as auth_router
from backend.app.controllers.classroom import router as classroom_router
from backend.app.controllers.reports import router as reports_router
from backend.app.controllers.ai import router as ai_router
from backend.app.controllers.buddies import router as buddies_router
from backend.app.controllers.engagement import router as engagement_router
from backend.app.controllers.notes import router as notes_router
from backend.app.controllers.wall import router as wall_router
from backend.app.controllers.join_codes import router as join_codes_router
from backend.app.controllers.profile import router as profile_router
from backend.app.controllers.teaching import router as teaching_router
from backend.app.controllers.demo import router as demo_router
from backend.app.controllers.leaves import router as leaves_router
from backend.app.controllers.extensions import router as extensions_router
from backend.app.controllers.privacy import router as privacy_router
from backend.app.controllers.ai_queue import router as ai_queue_router
from backend.app.errors import AppError, app_error_handler, validation_error_handler, http_error_handler
from backend.app.repositories.database import PROJECT_ROOT, initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="课堂情绪检查器 API",
    description="课程添加与加入码、进行中及课后 30 分钟的个人评价、匿名问题卡、课堂小结、个人笔记与回顾导出、学伴留言墙、看板与统计导出。教师仅能访问所授课程；学生仅能读取自己的情绪和笔记、名单内课堂的匿名问题及已确认学伴的留言墙。写操作需携带 X-Requested-With: EmojiClassroom。",
    version="0.22.0",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(classroom_router)
app.include_router(reports_router)
app.include_router(ai_router)
app.include_router(buddies_router)
app.include_router(engagement_router)
app.include_router(notes_router)
app.include_router(wall_router)
app.include_router(join_codes_router)
app.include_router(profile_router)
app.include_router(teaching_router)
app.include_router(demo_router)
app.include_router(leaves_router)
app.include_router(extensions_router)
app.include_router(privacy_router)
app.include_router(ai_queue_router)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/{unknown_path:path}", include_in_schema=False)
def api_not_found(unknown_path: str):
    return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "接口不存在", "data": None})


dist = PROJECT_ROOT / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
