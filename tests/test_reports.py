import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from test_classroom import actors, classroom_for, schedule, submit
from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect
from backend.app.services.reports import safe_csv_cell


@pytest.fixture
def report_data(actors):
    own = classroom_for(actors)
    second = classroom_for(actors)
    foreign = classroom_for(actors, 'other_teacher')
    anchor = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    with connect() as connection:
        for session, class_name in [(own, '一班'), (second, '二班'), (foreign, '其他教师班')]:
            connection.execute('UPDATE class_sessions SET class_name=? WHERE id=?', (class_name, session['id']))
        entries = [
            (actors['student']['user']['id'], own['id'], 'HAPPY', 'MANUAL', None, anchor + timedelta(hours=10)),
            (actors['other_student']['user']['id'], own['id'], 'SAD', 'MANUAL', None, anchor + timedelta(hours=10, minutes=30)),
            (None, second['id'], 'SURPRISED', 'AI', 0.95, anchor + timedelta(days=1, hours=10)),
            (actors['student']['user']['id'], foreign['id'], 'ANGRY', 'MANUAL', None, anchor + timedelta(hours=11)),
        ]
        for user_id, session_id, emotion, source, confidence, timestamp in entries:
            connection.execute('INSERT INTO emoji_records (user_id,session_id,emotion,source,confidence,recorded_at) VALUES (?,?,?,?,?,?)', (user_id, session_id, emotion, source, confidence, utc_text(timestamp)))
    return {'actors': actors, 'own': own, 'second': second, 'foreign': foreign, 'anchor': anchor, 'params': {'from_time': utc_text(anchor), 'to_time': utc_text(anchor + timedelta(days=3))}}


def report(data, role='admin', **filters):
    return data['actors'][role]['client'].get('/api/reports/statistics', params={**data['params'], **filters})


def test_multidimensional_summary_and_zero_filled_trend(report_data):
    response = report(report_data)
    assert response.status_code == 200
    data = response.json()['data']
    assert data['summary'] == {'total': 4, 'responding_students': 2, 'session_count': 3, 'course_count': 3, 'manual_count': 3, 'ai_count': 1}
    assert [item['total'] for item in data['trend']] == [3, 1, 0]
    assert sum(item['count'] for item in data['emotions']) == 4
    assert len(data['by_course']) == 3 and len(data['by_class']) == 3
    assert report(report_data, 'teacher').json()['data']['summary']['total'] == 3
    assert '其他教师班' not in report(report_data, 'teacher').text


def test_course_class_and_source_filters_are_composable(report_data):
    assert report(report_data, course_id=report_data['own']['course_id']).json()['data']['summary']['total'] == 2
    data = report(report_data, class_name='二班', source='AI').json()['data']
    assert data['summary']['total'] == 1 and data['summary']['responding_students'] == 0
    assert report(report_data, class_name='二班', source='MANUAL').json()['data']['summary']['total'] == 0
    assert report(report_data, class_name="x' OR 1=1 --").json()['data']['summary']['total'] == 0


def test_time_filters_are_half_open_and_accept_offsets(report_data):
    anchor = report_data['anchor']
    data = report(report_data, from_time=utc_text(anchor + timedelta(hours=10)), to_time=utc_text(anchor + timedelta(hours=10, minutes=30))).json()['data']
    assert data['summary']['total'] == 1
    from datetime import timezone
    offset = timezone(timedelta(hours=8))
    same = report(report_data, from_time=(anchor + timedelta(hours=10)).astimezone(offset).isoformat(), to_time=(anchor + timedelta(hours=10, minutes=30)).astimezone(offset).isoformat()).json()['data']
    assert same['summary'] == data['summary']
    assert same['filters']['from_time'].endswith('Z')


def test_invalid_times_sources_and_excessive_ranges_are_rejected(report_data):
    anchor = report_data['anchor']
    assert report(report_data, to_time=utc_text(anchor)).status_code == 422
    assert report(report_data, from_time='2026-11-02T10:00:00').status_code == 422
    assert report(report_data, source='UNKNOWN').status_code == 422
    assert report(report_data, class_name='   ').status_code == 422
    assert report(report_data, to_time=utc_text(anchor + timedelta(days=367))).status_code == 422
    assert report(report_data, bucket='hour', to_time=utc_text(anchor + timedelta(days=32))).status_code == 422
    assert len(report(report_data, bucket='hour').json()['data']['trend']) == 72


def test_teacher_scope_is_enforced_for_filters_and_export(report_data):
    teacher = report_data['actors']['teacher']['client']
    for route in ('/api/reports/statistics', '/api/reports/export'):
        assert teacher.get(route, params={**report_data['params'], 'course_id': report_data['foreign']['course_id']}).status_code == 403
        assert teacher.get(route, params={**report_data['params'], 'session_id': report_data['foreign']['id']}).status_code == 403
        assert teacher.get(route, params={**report_data['params'], 'course_id': 999999}).status_code == 404
    csv_response = teacher.get('/api/reports/export', params=report_data['params'])
    rows = list(csv.DictReader(io.StringIO(csv_response.content.decode('utf-8-sig'))))
    assert len(rows) == 3 and all(row['班级'] != '其他教师班' for row in rows)
    with connect() as connection:
        row = connection.execute("SELECT actor_id,detail FROM audit_logs WHERE action='EXPORT_CSV'").fetchone()
    assert row[0] == report_data['actors']['teacher']['user']['id']
    assert json.loads(row[1])['row_count'] == 3


def test_students_and_guests_cannot_read_reports_or_export(report_data, client):
    student = report_data['actors']['student']['client']
    for route in ('/api/reports/statistics', '/api/reports/export', f"/api/dashboard/realtime?session_id={report_data['own']['id']}"):
        assert student.get(route).status_code == 403
        assert client.get(route).status_code == 401


def test_csv_preserves_chinese_quotes_newlines_and_neutralizes_formulas(report_data):
    with connect() as connection:
        connection.execute('UPDATE courses SET name=? WHERE id=?', ('=HYPERLINK("https://example.invalid")', report_data['own']['course_id']))
        connection.execute('UPDATE class_sessions SET class_name=?,classroom=? WHERE id=?', (' \t=1+1', '教室,\n"一"', report_data['own']['id']))
    response = report_data['actors']['admin']['client'].get('/api/reports/export', params=report_data['params'])
    assert response.status_code == 200
    assert response.content.startswith(b'\xef\xbb\xbf')
    assert response.headers['content-type'].startswith('text/csv')
    assert 'attachment;' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'no-store'
    rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    own_rows = [row for row in rows if row['课堂ID'] == str(report_data['own']['id'])]
    assert len(own_rows) == 2
    assert own_rows[0]['课程'].startswith("'=HYPERLINK")
    assert own_rows[0]['班级'].startswith("' \t=")
    assert own_rows[0]['教室'] == '教室,\n"一"'
    assert all(len(row) == 13 and row['演示数据'] == '否' for row in rows)


@pytest.mark.parametrize('payload', ['=1+1', '+SUM(A1:A2)', '-2+3', '@SUM(1)', '\t=1', '\r=1', '\n+1', ' \x01=1', '\ufeff=1', '＝1+1'])
def test_csv_formula_prefixes_are_literal_text(payload):
    assert safe_csv_cell(payload).startswith("'")


def test_empty_csv_and_export_limit_do_not_silently_truncate(report_data, monkeypatch):
    admin = report_data['actors']['admin']['client']
    response = admin.get('/api/reports/export', params={**report_data['params'], 'class_name': '不存在的班级'})
    assert response.status_code == 200 and response.headers['x-export-count'] == '0'
    assert len(list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))) == 1
    monkeypatch.setattr('backend.app.services.reports.MAX_EXPORT_ROWS', 1)
    response = admin.get('/api/reports/export', params=report_data['params'])
    assert response.status_code == 422 and response.json()['code'] == 'EXPORT_TOO_LARGE'
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM audit_logs WHERE action='EXPORT_CSV'").fetchone()[0] == 1


def test_realtime_reflects_new_feedback_and_rejects_other_teachers(report_data):
    session = report_data['own']
    teacher = report_data['actors']['teacher']['client']
    route = f"/api/dashboard/realtime?session_id={session['id']}"
    before = teacher.get(route).json()['data']
    assert before['summary']['total'] == 2 and len(before['trend']) == 12
    assert sum(item['total'] for item in before['trend']) == 0
    schedule(report_data['actors'], session)
    assert submit(report_data['actors']['student'], session).status_code == 201
    after = teacher.get(route).json()['data']
    assert after['summary']['total'] == 3
    assert sum(item['total'] for item in after['trend']) == 1
    assert after['latest'][0]['emotion'] == 'HAPPY'
    assert report_data['actors']['other_teacher']['client'].get(route).status_code == 403
