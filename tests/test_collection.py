import json
import shutil
import time
from datetime import datetime, timedelta, timezone
import requests
import pytest
from config import DATA
from src.browser_bridge import Bridge,JOBS
from src.finance import parse_settlement,load_finance,settlement_schedule,ad_billing
from src.coupang_api import validate_snapshot


def test_rendered_screen_does_not_hide_failed_excel_download():
    from src.aside_collector import collection_issues
    source={'kind':'inventory','status':'수집 완료','downloads':[
        {'status':'파일 저장 완료','name':'inventory_health_sku_info_20261026.xlsx'},
        {'status':'다운로드 실패'}]}
    issues=collection_issues([source])
    assert len(issues)==1 and 'creturn' in issues[0]
    source['downloads'][1]={'status':'파일 저장 완료','name':'inventory_health_creturn_v2_info_20261026.xlsx'}
    assert collection_issues([source])==[]
    assert '본문 로딩 실패' in collection_issues([{'kind':'settlement','status':'쿠팡윙 본문 로딩 실패'}])[0]


def test_aside_result_does_not_depend_on_session_folder_and_failures_are_safe():
    from src.aside_collector import AsideCollectionError, read_collector_result
    payload = {'sources': [{'kind': 'inventory', 'status': '쿠팡윙 로그인 필요', 'text': ''}]}
    stdout = 'ASIDE_RESULT_JSON=' + json.dumps(payload, ensure_ascii=False) + '\n\x1b[2m[ok]\x1b[0m'
    assert read_collector_result(stdout) == payload
    with pytest.raises(AsideCollectionError, match='클릭 대상 확인 실패') as error:
        read_collector_result('RefStaleError: private session detail')
    assert 'private session detail' not in str(error.value)
    with pytest.raises(AsideCollectionError, match='결과를 읽지 못함'):
        read_collector_result('ASIDE_RESULT_JSON={not JSON')


def test_financial_observations_reconcile_and_reject_tampering():
    observations,errors=load_finance()
    assert not errors
    current=next(r for r in observations if r['start']=='2026-10-01')
    assert current['profit']==current['revenue']+current['expenses']+current['compensation']
    assert current['expenses']==current['ads']+current['fulfillment']+current['commission']
    assert all(r['profit']==r['revenue']+r['expenses']+r['compensation'] for r in observations)
    previous=next(r for r in observations if r['start']=='2026-09-01')
    assert previous['compensation']==27780 and previous['complete_month']
    schedule=settlement_schedule()
    assert len(schedule)>=22
    assert ('2026-11-03','주별',70,'2026-09-28~2026-09-30',27780) in schedule
    bill=ad_billing()
    assert bill['eligible']-bill['promotion']-bill['adjustment']+bill['vat']==bill['bill']
    assert bill['month']>='2026-10'
    text=(DATA/'evidence/settlement_20261001_20261022.txt').read_text(encoding='utf-8')
    with pytest.raises(ValueError,match='합계'):
        parse_settlement(text.replace('635,640','735,640'),'2026-10-23','test')
    with pytest.raises(ValueError): parse_settlement('로그인이 필요합니다','2026-10-23','test')


def test_failed_browser_refresh_keeps_last_valid_financial_observations(tmp_path):
    archived=DATA/'browser_snapshot_20261024074351_9ea1651c7942b3d733e6dccf.json'
    shutil.copyfile(archived,tmp_path/archived.name)
    (tmp_path/'browser_snapshot.json').write_text(json.dumps({
        'received_at':'2026-10-24T12:00:00+09:00',
        'sources':[{'kind':'settlement','status':'로그인 필요','text':''},
                   {'kind':'ad_billing','status':'로그인 필요','text':''}]
    }),encoding='utf-8')
    observations,errors=load_finance(tmp_path)
    assert not errors
    assert observations[0]['profit']==-107413
    assert ad_billing(tmp_path)['bill']==565037


def test_bridge_auth_atomic_completion_and_rejected_results(tmp_path):
    bridge=Bridge(port=0,data_dir=tmp_path).start()
    url=f'http://127.0.0.1:{bridge.port}'
    headers={'Authorization':'Bearer '+bridge.token}
    try:
        assert requests.get(url+'/job',timeout=3).status_code==403
        bridge.queue()
        job=requests.get(url+'/job',headers=headers,timeout=3).json()
        assert requests.get(url+'/job',headers=headers,timeout=3).json()=={}
        sources=[{**j,'status':'수집 완료','text':'test'} for j in JOBS]
        assert requests.post(url+'/result',headers=headers,json={'id':job['id'],'sources':sources[:1]},timeout=3).status_code==400
        assert not (tmp_path/'browser_snapshot.json').exists()
        assert requests.post(url+'/result',headers=headers,json={'id':job['id'],'sources':sources},timeout=3).status_code==200
        assert json.loads((tmp_path/'browser_snapshot.json').read_text(encoding='utf-8'))['id']==job['id']
        assert requests.post(url+'/result',headers=headers,json={'id':job['id'],'sources':sources},timeout=3).status_code==409
        bridge.pending={'id':'unanswered','created_at':(datetime.now(timezone.utc)-timedelta(seconds=61)).isoformat()}
        assert '응답 없음' in bridge.status()['status']
        bridge.active={'id':'expired','started':time.time()-Bridge.MAX_ACTIVE_SECONDS-1}
        assert '시간 초과' in bridge.status()['status']
    finally:
        bridge.server.shutdown(); bridge.server.server_close()


def test_api_schema_prevents_missing_fields_and_wrong_numbers():
    validate_snapshot([{'vendorItemId':123,'inventoryDetails':{'totalOrderableQuantity':0}}],[])
    validate_snapshot([], [{'orderId':123,'paidAt':1746093162000,'orderItems':[{'vendorItemId':1,'salesQuantity':1,'unitSalesPrice':'1000'}]}])
    with pytest.raises(RuntimeError): validate_snapshot([{'vendorItemId':123}],[])
    with pytest.raises(RuntimeError): validate_snapshot([], [{'orderId':123,'paidAt':1,'orderItems':[{'vendorItemId':1,'salesQuantity':-1,'unitSalesPrice':10}]}])
    with pytest.raises(RuntimeError): validate_snapshot([], [{'orderId':123,'paidAt':1,'orderItems':[{'vendorItemId':1,'salesQuantity':1,'unitSalesPrice':'-1000'}]}])


def test_scoped_chrome_settlement_does_not_replace_full_browser_snapshot(tmp_path):
    bridge=Bridge(port=0,data_dir=tmp_path).start()
    url=f'http://127.0.0.1:{bridge.port}'
    headers={'Authorization':'Bearer '+bridge.token,'X-Rocket-Settlement-Range':'1'}
    try:
        range_={'start':'2026-11-03','end':'2026-11-06'}
        bridge.queue(settlement_range=range_)
        job=requests.get(url+'/job',headers=headers,timeout=3).json()
        assert bridge.status()['period_connected']
        assert len(job['jobs'])==1 and job['jobs'][0]['range']==range_
        source={**job['jobs'][0],'status':'수집 완료','text':'Wing summary'}
        assert requests.post(url+'/result',headers=headers,json={'id':job['id'],'sources':[source]},timeout=3).status_code==200
        assert bridge.status()['sources']==[source]
        assert not (tmp_path/'browser_snapshot.json').exists()
    finally:
        bridge.server.shutdown();bridge.server.server_close()
