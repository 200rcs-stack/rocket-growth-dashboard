import json
import time
from config import RAW
from src.collector_relay import available
from src.compensation import parse_compensation, load_compensation


def test_api_recovers_from_transient_connection_failure(monkeypatch):
    import requests
    from src import coupang_api
    calls=[]
    class Response:
        status_code=200
        def json(self):
            return {'code':'200','data':[]}
    def get(*args, **kwargs):
        calls.append(1)
        if len(calls)==1:
            raise requests.ConnectionError('transient')
        return Response()
    monkeypatch.setattr(coupang_api.requests,'get',get)
    monkeypatch.setattr(coupang_api.time,'sleep',lambda _:None)
    reader=coupang_api.CoupangReader('A123','test-access','test-secret')
    assert reader.request('/test',{})['data']==[]
    assert len(calls)==2


def test_stale_relay_does_not_claim_connected(tmp_path):
    path=tmp_path/'chrome_relay_health.json'
    for connected, age, expected in [(True,0,True),(True,60,False),(False,0,False)]:
        path.write_text(json.dumps({'time':time.time()-age,'connected':connected}))
        assert available(tmp_path) is expected


def test_empty_valid_compensation_does_not_erase_prior_records():
    empty=RAW/'A00309576-INVENTORY_COMPENSATION-ko-2242a02f-ee4d-47c5-8dd1-659b8643f1f6.xlsx'
    assert parse_compensation(empty).empty
    previous, errors=load_compensation()
    assert not errors
    assert len(previous)==13 and previous.compensation_amount.sum()==27780


def test_aside_collection_does_not_require_chrome(monkeypatch):
    from src import browser_collect as module
    expected={'status':'수집 완료','sources':[{'kind':'settlement','captured_at':'aside-time'}]}
    monkeypatch.setattr(module,'collect_aside',lambda:expected)
    assert module.collect() is expected


def test_one_aside_timeout_preserves_other_sources(tmp_path, monkeypatch):
    from src import aside_collector as module
    original=module.collect
    calls=[]
    def one(*,data_dir,timeout,kinds):
        kind=kinds[0]
        calls.append(kind)
        if kind=='settlement':
            raise RuntimeError('timeout')
        downloads=[{'status':'파일 저장 완료','name':prefix+'test.xlsx'}
                   for prefix in module.REQUIRED_DOWNLOADS.get(kind,())]
        return {'sources':[{'kind':kind,'status':'수집 완료','text':'verified',
                            'captured_at':'2026-10-27T12:00:00+09:00','downloads':downloads}]}
    monkeypatch.setattr(module,'collect',one)
    result=original(data_dir=tmp_path)
    assert len(calls)==5 and len(result['sources'])==5
    assert len(result['issues'])==1 and '정산' in result['issues'][0]
    saved=json.loads((tmp_path/'browser_snapshot.json').read_text(encoding='utf-8'))
    assert sum(s['status']=='수집 완료' for s in saved['sources'])==4
