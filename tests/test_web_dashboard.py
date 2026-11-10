import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from src import ai_advisor as ai


def snapshot():
    return {'summary':{'missing_costs':4,'restock':2,'out_of_stock':1,'return_cases':8,'overdue_returns':3},
      'sources':[{'id':k,'time':'2026-10-25T21:00:00+09:00'} for k in ('inventory','returns','ads')],
      'gaps':[{'reason':'원가 확인 필요'}],'ads':None,'finance':[],'inventory':[], 'returns':[]}


def model_response():
    card={'title':'자료 점검','action':'입력 내역을 확인하세요.','why':'확인 후 판단하기 위한 제안입니다.','priority':'보통',
          'verify':'최신 원본을 대조하세요.','stop_condition':'원가가 없으면 판단을 보류하세요.','success_check':'원본 대조 완료'}
    return {'ads':card.copy(),'inventory':card.copy(),'returns':card.copy(),
            'plan':[{'day':d,'action':'원본 확인','success_check':'확인표 작성','source_ids':['inventory']} for d in ('첫날','중반','마지막 날')]}


def setup(monkeypatch,tmp_path,body):
    monkeypatch.setattr(ai,'DATA',tmp_path)
    monkeypatch.setattr(ai,'env_key',lambda key:'test-key' if key=='OPENAI_API_KEY' else None)
    response=Mock(status_code=200)
    response.json.return_value={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(body)}]}]}
    post=Mock(return_value=response);monkeypatch.setattr(ai.requests,'post',post)
    return post


def test_ai_numbers_are_deterministic_and_cache_prevents_charge(monkeypatch,tmp_path):
    post=setup(monkeypatch,tmp_path,model_response())
    a=ai.advice(snapshot())
    assert a['status']=='ready'
    assert '90일 이상' in a['advice'][2]['evidence'] and '3건' in a['advice'][2]['evidence']
    assert a['advice'][2]['source_ids']==['returns']
    assert ai.advice(snapshot())==a and post.call_count==1
    unchanged=snapshot();unchanged['sources'][0]['time']='2026-10-25T22:00:00+09:00'
    assert ai.advice(unchanged)==a and post.call_count==1
    assert post.call_args.kwargs['json']['store'] is False


def test_ai_rejects_unsupported_numeric_claim(monkeypatch,tmp_path):
    body=model_response();body['returns']['action']='반품 999건을 처리하세요.'
    setup(monkeypatch,tmp_path,body)
    result=ai.advice(snapshot())
    assert result['status']=='error'
    assert not (tmp_path/'ai_advice.json').exists()


def test_ai_rejects_unknown_source(monkeypatch,tmp_path):
    body=model_response();body['plan'][0]['source_ids']=['invented']
    setup(monkeypatch,tmp_path,body)
    assert ai.advice(snapshot())['status']=='error'

@pytest.mark.parametrize('field',['verify','stop_condition','success_check'])
def test_ai_rejects_invented_numbers_in_review_conditions(monkeypatch,tmp_path,field):
    body=model_response();body['ads'][field]='매출을 999원으로 확정합니다.'
    setup(monkeypatch,tmp_path,body)
    assert ai.advice(snapshot())['status']=='error'


def test_file_clock_is_explicit_for_other_pc_timezones():
    from src.web_snapshot import explicit_kst
    assert explicit_kst('2026-10-26T10:56:06')=='2026-10-26T10:56:06+09:00'
    assert explicit_kst('2026-10-26T01:56:06Z')=='2026-10-26T10:56:06+09:00'
    assert explicit_kst(None) is None
