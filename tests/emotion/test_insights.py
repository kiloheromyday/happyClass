from datetime import datetime, UTC, timedelta
import json
from uuid import uuid4

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from backend.app.emotion.insights.analysis import detect_signals
from tests.test_classroom import actors, classroom_for, HEADERS

START = datetime(2026,11,1,1,tzinfo=UTC)


def setup_session(actors, monkeypatch):
    session=classroom_for(actors)
    with connect() as db:
        db.execute('UPDATE class_sessions SET starts_at=?,ends_at=? WHERE id=?',
                   (utc_text(START),utc_text(START+timedelta(minutes=40)),session['id']))
    monkeypatch.setattr('backend.app.emotion.insights.service.now_utc',lambda:START+timedelta(minutes=50))
    return session,actors['teacher']['client'],f"/api/sessions/{session['id']}/insights"


def records(session, minute, emotion='SAD', count=5, source='MANUAL', demo=0, user_id=None):
    with connect() as db:
        if user_id is None:
            user_id=db.execute("SELECT id FROM users WHERE role='STUDENT' LIMIT 1").fetchone()[0]
        db.executemany('''INSERT INTO emoji_records(session_id,user_id,emotion,source,confidence,device_id,recorded_at,is_demo)
            VALUES (?,?,?,?,?,?,?,?)''',[(session['id'],user_id if source=='MANUAL' else None,emotion,source,.95 if source=='AI' else None,
            'secret-device',utc_text(START+timedelta(minutes=minute,seconds=index)),demo) for index in range(count)])


def entry(kind='PHASE', **changes):
    return dict({'kind':kind,'title':'概念讲解' if kind=='PHASE' else '补充图示','content':'教学记录',
                 'start_minute':0 if kind=='PHASE' else 20,'end_minute':10 if kind=='PHASE' else 20,
                 'status':'DONE','outcome':'','version':0,'request_id':str(uuid4())},**changes)


def test_signals_separate_sources_break_on_gaps_and_ignore_partial_windows():
    def frame(index, manual, ai, complete=True):
        return {'from_time':str(index),'to_time':str(index+1),'start_minute':index,'end_minute':index+1,'complete':complete,
                'sources':{'MANUAL':{'total':manual[0],'concern_count':manual[1]},'AI':{'total':ai[0],'concern_count':ai[1]}}}
    rules={'min_records':5,'concern_ratio':.6,'consecutive_windows':2}
    frames=[frame(0,(5,3),(20,0)),frame(1,(5,4),(20,0)),frame(2,(0,0),(5,5)),
            frame(3,(5,5),(5,5)),frame(4,(5,5),(5,5),False)]
    result=detect_signals(frames,rules)
    assert len(result)==2
    assert result[0]['source']=='MANUAL' and result[0]['total']==10 and result[0]['concern_count']==7
    assert result[1]['source']=='AI' and result[1]['start_minute']==2 and result[1]['windows']==2
    assert not detect_signals([frame(0,(4,4),(0,0)),frame(1,(4,4),(0,0))],rules)
    assert not detect_signals([frame(0,(7,4),(0,0)),frame(1,(7,4),(0,0))],rules)


def test_aggregate_analysis_signals_filters_and_privacy(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    records(session,1);records(session,6)
    records(session,1,'HAPPY',20,'AI')
    records(session,6,'ANGRY',10,'AI',demo=1)
    records(session,50,'ANGRY',10)  # exclusive snapshot edge
    response=client.get(url)
    assert response.status_code==200
    data=response.json()['data']
    assert data['summary']['total']==30 and data['summary']['demo_count']==0
    assert data['sources']['MANUAL']['total']==10 and data['sources']['AI']['total']==20
    assert len(data['signals'])==1 and data['signals'][0]['source']=='MANUAL'
    assert data['signals'][0]['concern_ratio']==1
    text=json.dumps(data)
    assert not any(key in text for key in ('"user_id"','"username"','"device_id"','secret-device','"record_id"'))
    assert client.get(url,params={'data_scope':'DEMO'}).json()['data']['summary']['total']==10
    assert client.get(url,params={'source':'AI'}).json()['data']['signals']==[]
    with connect() as db:
        db.execute('INSERT INTO session_privacy VALUES (?,?,?,?,?)',(session['id'],'AGGREGATE',1,utc_text(START),actors['admin']['user']['id']))
    assert client.get(url).json()['data']['privacy_mode']=='AGGREGATE'


def test_rules_version_conflicts_invalid_values_and_recalculation(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    for minute in (1,6):records(session,minute)
    payload={'bucket_minutes':5,'min_records':6,'concern_ratio':.6,'consecutive_windows':2,'version':0}
    assert client.put(url+'/rules',json=payload,headers=HEADERS).status_code==200
    assert client.get(url).json()['data']['signals']==[]
    assert client.put(url+'/rules',json=payload,headers=HEADERS).status_code==409
    assert client.get(url).json()['data']['rules']['min_records']==6
    for change in ({'min_records':2},{'bucket_minutes':2},{'concern_ratio':1.1},{'consecutive_windows':1},{'min_records':True}):
        assert client.put(url+'/rules',json={**payload,**change,'version':1},headers=HEADERS).status_code==422


def test_entry_idempotency_overlap_edit_conflict_and_delete(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    payload=entry();created=client.post(url+'/entries',json=payload,headers=HEADERS)
    assert created.status_code==201
    item=created.json()['data'];path=url+f"/entries/{item['id']}"
    assert client.post(url+'/entries',json=payload,headers=HEADERS).json()['data']['id']==item['id']
    assert client.post(url+'/entries',json={**payload,'title':'不同内容'},headers=HEADERS).status_code==409
    assert client.post(url+'/entries',json=entry(start_minute=5,end_minute=15),headers=HEADERS).status_code==409
    assert client.post(url+'/entries',json=entry(start_minute=10,end_minute=20),headers=HEADERS).status_code==201
    edit={**payload,'title':'新版教学环节','version':1}
    assert client.put(path,json=edit,headers=HEADERS).json()['data']['version']==2
    assert client.put(path,json=edit,headers=HEADERS).status_code==409
    assert client.delete(path+'?version=1',headers=HEADERS).status_code==409
    assert client.delete(path+'?version=2',headers=HEADERS).status_code==200
    assert client.delete(path+'?version=2',headers=HEADERS).status_code==404
    initialize_database()
    assert len(client.get(url).json()['data']['entries'])==1


def test_action_equal_windows_source_isolation_and_sample_sufficiency(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    records(session,15,'SAD',5);records(session,19,'SAD',5)
    records(session,20,'HAPPY',5);records(session,24,'HAPPY',5)
    records(session,25,'ANGRY',20)  # excluded from after [20,25)
    records(session,19,'ANGRY',20,'AI')  # no after AI sample
    records(session,24,'ANGRY',20,'MANUAL',demo=1)
    payload=entry('ACTION')
    assert client.post(url+'/entries',json=payload,headers=HEADERS).status_code==201
    data=client.get(url).json()['data'];action=data['entries'][0]
    manual,ai=action['comparison']['sources']
    assert manual['before']['total']==10 and manual['after']['total']==10
    assert manual['status']=='COMPARABLE' and manual['change_percentage_points']==-100
    assert ai['status']=='INSUFFICIENT_DATA' and ai['change_percentage_points'] is None
    assert action['comparison']['complete']
    assert client.get(url,params={'comparison_minutes':6}).status_code==422
    assert client.post(url+'/entries',json=entry('ACTION',start_minute=49,end_minute=49),headers=HEADERS).status_code==201
    late=client.get(url).json()['data']['entries'][-1]
    assert not late['comparison']['complete']
    assert all(item['change_percentage_points'] is None for item in late['comparison']['sources'])


def test_roles_csrf_boundaries_and_cross_session_entry_ids(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    for who in ('student','other_teacher'):
        assert actors[who]['client'].get(url).status_code==403
        assert actors[who]['client'].get(url+'/export').status_code==403
        assert actors[who]['client'].post(url+'/entries',json=entry(),headers=HEADERS).status_code==403
    assert client.post(url+'/entries',json=entry()).status_code==403
    assert client.post(url+'/entries',json=entry(end_minute=41),headers=HEADERS).status_code==422
    assert client.post(url+'/entries',json=entry('ACTION',start_minute=51,end_minute=51),headers=HEADERS).status_code==422
    assert client.post(url+'/entries',json=entry('ACTION',start_minute=71,end_minute=71,status='PLANNED'),headers=HEADERS).status_code==422
    assert client.post(url+'/entries',json=entry('ACTION',start_minute=51,end_minute=51,status='PLANNED'),headers=HEADERS).status_code==201
    another=classroom_for(actors)
    item=client.post(url+'/entries',json=entry(),headers=HEADERS).json()['data']
    other_url=f"/api/sessions/{another['id']}/insights/entries/{item['id']}"
    assert client.put(other_url,json=entry(version=1),headers=HEADERS).status_code==404
    assert client.delete(other_url+'?version=1',headers=HEADERS).status_code==404
    assert client.get('/api/sessions/999999/insights').status_code==404
    assert client.get(url,params={'source':'WEBCAM'}).status_code==422


def test_phase_links_export_escaping_no_data_and_long_session_bounds(actors,monkeypatch):
    session,client,url=setup_session(actors,monkeypatch)
    assert client.get(url).json()['data']['signals']==[]
    for minute in (1,6):records(session,minute)
    assert client.post(url+'/entries',json=entry(title='=HYPERLINK("test")',content='+unsafe'),headers=HEADERS).status_code==201
    data=client.get(url).json()['data']
    assert data['signals'][0]['phase_titles']==['=HYPERLINK("test")']
    response=client.get(url+'/export')
    assert response.status_code==200 and response.headers['content-type'].startswith('text/csv')
    text=response.content.decode('utf-8-sig')
    assert "'=HYPERLINK" in text and "'+unsafe" in text and 'secret-device' not in text
    assert '单靠这组数判断不了是不是调整起了作用' in text
    with connect() as db:
        db.execute('UPDATE class_sessions SET starts_at=? WHERE id=?',(utc_text(START-timedelta(days=40)),session['id']))
    assert len(client.get(url).json()['data']['frames'])<=360


def test_explicit_synthetic_seed_is_idempotent_and_has_working_comparisons(actors,monkeypatch):
    from scripts.emotion.seed_insights_demo import seed
    monkeypatch.setattr('scripts.emotion.seed_insights_demo.now_utc',lambda:START+timedelta(minutes=60))
    monkeypatch.setattr('backend.app.emotion.insights.service.now_utc',lambda:START+timedelta(minutes=60))
    first=seed('teacher');second=seed('teacher')
    assert first['created'] and not second['created'] and first['session_id']==second['session_id']
    url=f"/api/sessions/{first['session_id']}/insights"
    client=actors['teacher']['client']
    assert client.get(url).json()['data']['summary']['total']==0
    data=client.get(url,params={'data_scope':'DEMO'}).json()['data']
    assert data['summary']['total']==data['summary']['demo_count']==270
    assert len(data['signals'])==2 and len(data['entries'])==4
    action=next(item for item in data['entries'] if item['kind']=='ACTION')
    assert all(metric['change_percentage_points']==-100 for metric in action['comparison']['sources'])
