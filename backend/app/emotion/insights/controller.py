from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import AppError, success
from backend.app.emotion.insights.models import InsightEntry, InsightRules
from backend.app.emotion.insights import service

router = APIRouter(prefix='/api/sessions/{session_id}/insights', tags=['课堂情绪洞察与教学跟进'])
staff = require_roles('TEACHER','ADMIN')


def options(source: Literal['ALL','MANUAL','AI']='ALL', data_scope: Literal['REAL','DEMO','ALL']='REAL',
            comparison_minutes: int=Query(default=5,ge=5,le=15)):
    if comparison_minutes not in (5,10,15):
        raise AppError(422,'INVALID_COMPARISON_WINDOW','对比窗口请选择 5、10 或 15 分钟')
    return {'source':source,'data_scope':data_scope,'comparison_minutes':comparison_minutes}


@router.get('')
def get(session_id: int=Path(gt=0), filters=Depends(options), user=Depends(staff)):
    return success(service.analysis(session_id,user,**filters))


@router.put('/rules', dependencies=[Depends(require_same_origin)])
def rules(payload: InsightRules, session_id: int=Path(gt=0), user=Depends(staff)):
    return success(service.save_rules(session_id,payload,user),'洞察规则已保存')


@router.post('/entries', status_code=201, dependencies=[Depends(require_same_origin)])
def create(payload: InsightEntry, session_id: int=Path(gt=0), user=Depends(staff)):
    return success(service.save_entry(session_id,payload,user),'教学记录已保存')


@router.put('/entries/{entry_id}', dependencies=[Depends(require_same_origin)])
def update(payload: InsightEntry, session_id: int=Path(gt=0), entry_id: int=Path(gt=0), user=Depends(staff)):
    return success(service.save_entry(session_id,payload,user,entry_id),'教学记录已更新')


@router.delete('/entries/{entry_id}', dependencies=[Depends(require_same_origin)])
def delete(session_id: int=Path(gt=0), entry_id: int=Path(gt=0), version: int=Query(ge=1), user=Depends(staff)):
    return success(service.delete_entry(session_id,entry_id,version,user),'教学记录已删除')


@router.get('/export')
def export(session_id: int=Path(gt=0), filters=Depends(options), user=Depends(staff)):
    content,count = service.export_report(session_id,user,**filters)
    return Response(content,media_type='text/csv',headers={
        'Content-Disposition':f'attachment; filename="classroom-insights-{session_id}.csv"','X-Export-Count':str(count)})
