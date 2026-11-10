from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import uuid4

from backend.app.emotion.lab import repository as repo
from backend.app.emotion.lab import worker
from backend.app.emotion.lab.metrics import distance
from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect
from tests.test_classroom import actors, classroom_for, HEADERS
from tests.emotion.test_insights import records, START

BASE='/api/emotion-lab'


def prepare(actors, monkeypatch):
    sessions=[]
    for index in range(2):
        session=classroom_for(actors)
        with connect() as db:
            db.execute('UPDATE class_sessions SET starts_at=?,ends_at=? WHERE id=?',
                       (utc_text(START),utc_text(START+timedelta(minutes=40)),session['id']))
        for minute in (1,6,11,16,21,26,31,36):
            records(session,minute,'SAD' if minute<20 else 'HAPPY',5,'MANUAL')
            records(session,minute,'NEUTRAL',10,'AI',demo=1)
        sessions.append(session)
    clock=lambda:START+timedelta(hours=1)
    monkeypatch.setattr('backend.app.emotion.lab.service.now_utc',clock)
    monkeypatch.setattr('backend.app.emotion.lab.worker.now_utc',clock)
    return actors['teacher']['client'],sessions


def payload(sessions,**extra):
    return dict({'title':'两节课堂对比','question':'查看共同出现的关注时段','tags':['复盘'],
                 'session_ids':[item['id'] for item in sessions],'baseline_ids':[sessions[0]['id']],
                 'settings':{'source':'ALL','data_scope':'REAL','alignment':'RELATIVE'},
                 'version':0,'request_id':str(uuid4())},**extra)


def create_run(client,sessions):
    response=client.post(BASE+'/studies',json=payload(sessions),headers=HEADERS)
    assert response.status_code==201,response.text
    study=response.json()['data']
    response=client.post(BASE+f"/studies/{study['id']}/runs",json={'version':study['version'],'request_id':str(uuid4())},headers=HEADERS)
    assert response.status_code==202,response.text
    return study,response.json()['data']


def test_study_to_worker_report_notes_exports_and_snapshot(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    study,job=create_run(client,sessions)
    assert worker.run_once()
    state=client.get(BASE+f"/jobs/{job['id']}").json()['data']
    assert state['state']=='SUCCEEDED',state
    assert state['progress']==100 and len(state['events'])>=5
    path=BASE+f"/reports/{state['report_id']}"
    response=client.get(path);assert response.status_code==200,response.text
    report=response.json()['data'];data=report['result']
    assert data['summary']['total_records']==80 and data['summary']['demo_records']==0
    assert data['sources']['MANUAL']['equal_weight_concern_ratio']==.5
    assert data['sources']['AI']['pooled']['total']==0
    assert len(data['alignment']['rows'])==2 and len(data['alignment']['patterns'])>=1
    assert data['groups'][0]['equal_weight_change_pp']==0
    content=json.dumps(report)
    assert not any(value in content for value in ('"user_id"','"username"','secret-device','"device_id"'))
    digest_data={key:value for key,value in data.items() if key!='fingerprint'}
    assert hashlib.sha256(repo.encode(digest_data).encode()).hexdigest()==report['fingerprint']
    records(sessions[0],2,'ANGRY',5)
    assert client.get(path).json()['data']['result']['summary']['total_records']==80
    note={'section':'FINDING','content':'<script>example</script>','version':0,'request_id':str(uuid4())}
    annotation=client.post(path+'/annotations',json=note,headers=HEADERS)
    assert annotation.status_code==201,annotation.text
    assert client.post(path+'/annotations',json=note,headers=HEADERS).json()['data']['id']==annotation.json()['data']['id']
    reviewed=client.put(path,json={'title':'=报告标题','status':'REVIEWED','bookmarked':True,'conclusion':'核对了样本与来源','version':1},headers=HEADERS)
    assert reviewed.status_code==200,reviewed.text
    assert client.put(path,json={'title':'旧版本','status':'DRAFT','version':1},headers=HEADERS).status_code==409
    for format in ('csv','json','html'):
        response=client.get(path+'/export',params={'format':format})
        assert response.status_code==200,response.text
        if format=='html':assert '<script>example</script>' not in response.text and '&lt;script&gt;' in response.text
        if format=='csv':assert "'=报告标题" in response.content.decode('utf-8-sig')
    assert client.get(path+f"/compare/{report['id']}").json()['data']['compatible']


def test_role_ownership_reassignment_and_no_csrf_bypass(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    for name in ('student','other_teacher'):
        other=actors[name]['client']
        expected=403 if name=='student' else 200
        assert other.get(BASE+'/catalog').status_code==expected
        assert other.post(BASE+'/studies',json=payload(sessions),headers=HEADERS).status_code==403
    assert client.post(BASE+'/studies',json=payload(sessions)).status_code==403
    study,job=create_run(client,sessions)
    assert actors['other_teacher']['client'].get(BASE+f"/studies/{study['id']}").status_code==404
    assert worker.run_once()
    report_id=client.get(BASE+f"/jobs/{job['id']}").json()['data']['report_id']
    assert actors['admin']['client'].get(BASE+f'/reports/{report_id}').status_code==404
    with connect() as db:
        db.execute('UPDATE courses SET teacher_id=? WHERE id=?',(actors['other_teacher']['user']['id'],sessions[0]['course_id']))
    assert client.get(BASE+f'/reports/{report_id}').status_code==403
    assert client.get(BASE+f'/reports/{report_id}/export').status_code==403


def test_versions_idempotency_archive_preview_and_selection_validation(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    body=payload(sessions)
    response=client.post(BASE+'/studies',json=body,headers=HEADERS);study=response.json()['data']
    assert client.post(BASE+'/studies',json=body,headers=HEADERS).json()['data']['id']==study['id']
    assert client.post(BASE+'/studies',json={**body,'title':'不一样'},headers=HEADERS).status_code==409
    assert client.post(BASE+'/preview',json=body,headers=HEADERS).json()['data']['baseline_count']==1
    path=BASE+f"/studies/{study['id']}"
    assert client.put(path,json={**body,'version':1},headers=HEADERS).status_code==200
    assert client.put(path,json={**body,'version':1},headers=HEADERS).status_code==409
    assert client.put(path+'/archive',json={'version':2,'archived':True},headers=HEADERS).status_code==200
    assert client.post(path+'/runs',json={'version':3,'request_id':str(uuid4())},headers=HEADERS).status_code==409
    assert client.put(path+'/archive',json={'version':3,'archived':False},headers=HEADERS).status_code==200
    for change in ({'session_ids':[]},{'session_ids':[sessions[0]['id']]*2},{'baseline_ids':[999999]}, {'tags':['a','a']}):
        assert client.post(BASE+'/studies',json={**body,**change},headers=HEADERS).status_code==422


def test_cancel_retry_failure_and_expired_lease_recovery(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    study,job=create_run(client,sessions)
    path=BASE+f"/jobs/{job['id']}"
    assert client.post(path+'/cancel',headers=HEADERS).json()['data']['state']=='CANCELLED'
    assert not worker.run_once()
    assert client.post(path+'/retry',headers=HEADERS).status_code==409
    _,second=create_run(client,sessions)
    original=worker.build_result
    monkeypatch.setattr(worker,'build_result',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('private internal detail')))
    assert worker.run_once()
    state=client.get(BASE+f"/jobs/{second['id']}").json()['data']
    assert state['state']=='FAILED' and 'private internal detail' not in json.dumps(state)
    monkeypatch.setattr(worker,'build_result',original)
    assert client.post(BASE+f"/jobs/{second['id']}/retry",headers=HEADERS).status_code==200
    claimed=worker.claim();assert claimed['id']==second['id']
    with connect() as db:
        db.execute('UPDATE lab_jobs SET lease_until=? WHERE id=?',(utc_text(START),second['id']))
    assert worker.run_once()
    assert client.get(BASE+f"/jobs/{second['id']}").json()['data']['state']=='SUCCEEDED'


def test_distribution_distance_and_phase_alignment(actors,monkeypatch):
    assert distance({'HAPPY':10},{'HAPPY':10},3)['total_variation']==0
    assert distance({'HAPPY':10},{'SAD':10},3)['jensen_shannon_bits']==1
    assert distance({'HAPPY':1},{'SAD':10},3)['status']=='INSUFFICIENT_DATA'
    client,sessions=prepare(actors,monkeypatch)
    from backend.app.emotion.insights.models import InsightEntry
    from backend.app.emotion.insights.service import save_entry
    for session in sessions:
        save_entry(session['id'],InsightEntry(kind='PHASE',title='概念讲解',start_minute=0,end_minute=20,request_id=uuid4()),actors['teacher']['user'])
    body=payload(sessions,settings={'alignment':'PHASE','data_scope':'REAL'})
    study=client.post(BASE+'/studies',json=body,headers=HEADERS).json()['data']
    job=client.post(BASE+f"/studies/{study['id']}/runs",json={'version':1,'request_id':str(uuid4())},headers=HEADERS).json()['data']
    assert worker.run_once()
    report_id=client.get(BASE+f"/jobs/{job['id']}").json()['data']['report_id']
    result=client.get(BASE+f'/reports/{report_id}').json()['data']['result']
    assert result['alignment']['columns'][0]['label']=='概念讲解'
    assert result['alignment']['rows'][0]['cells'][0]['sources']['MANUAL']['total']==20


def test_integrity_history_and_archived_report_lifecycle(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    study,job=create_run(client,sessions)
    assert worker.run_once()
    identifier=client.get(BASE+f"/jobs/{job['id']}").json()['data']['report_id']
    path=BASE+f'/reports/{identifier}'
    checked=client.get(path+'/integrity').json()['data']
    assert checked['passed'] and len(checked['checks'])==10
    assert client.get(BASE+'/storage').json()['data']['reports']==1
    history=client.get(BASE+f"/studies/{study['id']}/history").json()['data']
    assert history['items'][0]['report_id']==identifier
    assert client.delete(path+'?version=1',headers=HEADERS).status_code==409
    assert client.put(path,json={'title':'归档快照','status':'ARCHIVED','version':1},headers=HEADERS).status_code==200
    assert client.delete(path+'?version=1',headers=HEADERS).status_code==409
    note={'section':'CONTEXT','content':'不能修改归档批注','version':0,'request_id':str(uuid4())}
    assert client.post(path+'/annotations',json=note,headers=HEADERS).status_code==409
    assert client.delete(path+'?version=2',headers=HEADERS).status_code==200
    assert client.get(path).status_code==404
    assert client.get(BASE+'/storage').json()['data']['reports']==0
    state=client.get(BASE+f"/jobs/{job['id']}").json()['data']
    assert state['state']=='SUCCEEDED' and state['report_id'] is None
    assert state['events'][-1]['code']=='REPORT_REMOVED'


def test_cancel_running_job_snapshot_tamper_and_incompatible_comparison(actors,monkeypatch):
    client,sessions=prepare(actors,monkeypatch)
    study,job=create_run(client,sessions)
    original=worker.build_result
    def cancel_during_run(definition,user,cutoff,checkpoint):
        client.post(BASE+f"/jobs/{job['id']}/cancel",headers=HEADERS)
        checkpoint(20,'检查取消')
    monkeypatch.setattr(worker,'build_result',cancel_during_run)
    assert worker.run_once()
    assert client.get(BASE+f"/jobs/{job['id']}").json()['data']['state']=='CANCELLED'
    monkeypatch.setattr(worker,'build_result',original)
    ids=[]
    for scope in ('REAL','ALL'):
        body=payload(sessions,settings={'data_scope':scope})
        current=client.post(BASE+'/studies',json=body,headers=HEADERS).json()['data']
        queued=client.post(BASE+f"/studies/{current['id']}/runs",json={'version':1,'request_id':str(uuid4())},headers=HEADERS).json()['data']
        assert worker.run_once()
        ids.append(client.get(BASE+f"/jobs/{queued['id']}").json()['data']['report_id'])
    compared=client.get(BASE+f'/reports/{ids[0]}/compare/{ids[1]}').json()['data']
    assert not compared['compatible'] and compared['different_settings']==['data_scope']
    assert all(item['equal_weight_change_pp'] is None for item in compared['sources'])
    with connect() as db:
        text=db.execute('SELECT result FROM lab_reports WHERE id=?',(ids[0],)).fetchone()[0]
        data=json.loads(text);data['summary']['total_records']+=1
        db.execute('UPDATE lab_reports SET result=? WHERE id=?',(repo.encode(data),ids[0]))
    integrity=client.get(BASE+f'/reports/{ids[0]}/integrity').json()['data']
    assert not integrity['passed'] and not integrity['checks'][0]['passed']
