import csv
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, Path, Response
from pydantic import Field

from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import AppError, success
from backend.app.models.auth import StrictModel
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect
from backend.app.repositories.classroom import audit
from backend.app.repositories.privacy import policy
from backend.app.services.classroom import accessible_session

router = APIRouter(prefix='/api/privacy', tags=['匿名与聚合模式'])


class PrivacyPolicy(StrictModel):
    mode: Literal['STANDARD', 'ANONYMOUS', 'AGGREGATE']
    version: int = Field(ge=0, strict=True)


@router.get('/sessions/{session_id}')
def get_policy(session_id: int = Path(gt=0), user=Depends(current_user)):
    with connect() as connection:
        accessible_session(connection, session_id, user)
        return success(policy(connection, session_id))


@router.put('/sessions/{session_id}', dependencies=[Depends(require_same_origin)])
def set_policy(payload: PrivacyPolicy, session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        accessible_session(connection, session_id, user)
        previous = policy(connection, session_id)
        if previous['version'] != payload.version:
            raise AppError(409, 'PRIVACY_CONFLICT', '隐私设置已更新，请刷新后重试')
        rank = {'STANDARD': 0, 'ANONYMOUS': 1, 'AGGREGATE': 2}
        if rank[payload.mode] < rank[previous['mode']] and connection.execute('SELECT 1 FROM emoji_records WHERE session_id=? LIMIT 1', (session_id,)).fetchone():
            raise AppError(409, 'PRIVACY_DOWNGRADE', '课堂已有反馈，不能降低隐私保护等级')
        connection.execute('''INSERT INTO session_privacy(session_id,mode,version,updated_at,updated_by)
            VALUES (?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET mode=excluded.mode,
            version=excluded.version,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
            (session_id, payload.mode, payload.version + 1, utc_text(now_utc()), user['id']))
        audit(connection, user['id'], 'PRIVACY_POLICY_UPDATED', {'session_id': session_id, 'mode': payload.mode})
        return success(policy(connection, session_id), '课堂反馈隐私设置已保存')


@router.get('/sessions/{session_id}/export')
def export_aggregate(session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        accessible_session(connection, session_id, user)
        records = connection.execute('SELECT emotion,source,count(*) FROM emoji_records WHERE session_id=? GROUP BY emotion,source ORDER BY emotion,source', (session_id,)).fetchall()
        buffer = StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['课堂ID', '情绪', '来源', '记录数'])
        writer.writerows((session_id, *item) for item in records)
        audit(connection, user['id'], 'EXPORT_AGGREGATE_CSV', {'session_id': session_id, 'groups': len(records)})
    return Response(('\ufeff' + buffer.getvalue()).encode('utf-8'), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="aggregate-{session_id}.csv"', 'X-Export-Count': str(len(records))})
