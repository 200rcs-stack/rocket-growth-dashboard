import json
from unittest.mock import Mock
from config import now
from src import web_sync


def test_partial_full_refresh_reports_stages_duration_and_keeps_failed_scope_visible(monkeypatch,tmp_path):
    from src import browser_collect
    monkeypatch.setattr(web_sync,'DATA',tmp_path)
    (tmp_path/'api_snapshot.json').write_text(json.dumps({'fetched_at':now().isoformat(),'product_details':{}}))
    monkeypatch.setattr(browser_collect,'collect',lambda:{'status':'일부 확인 필요','issues':['정산 화면: 로그인 필요']})
    monkeypatch.setattr(web_sync,'build_snapshot',lambda:{'summary':{}})
    monkeypatch.setattr(web_sync,'advice',lambda snapshot:{'status':'ready'})
    sync=object.__new__(web_sync.Sync);sync.request=Mock();sync.publish=Mock()
    sync.run_job({'id':'test','mode':'full'})
    updates=[call.kwargs['json'] for call in sync.request.call_args_list]
    assert updates[0]['state']=='running'
    assert any('지원 엑셀' in update['message'] for update in updates)
    assert updates[-1]['state']=='partial'
    assert '로그인 필요' in updates[-1]['message']
    assert isinstance(updates[-1]['duration_seconds'],int) and updates[-1]['duration_seconds']>=0
    sync.publish.assert_called_once()


def test_quick_refresh_does_not_call_paid_ai(monkeypatch,tmp_path):
    monkeypatch.setattr(web_sync,'DATA',tmp_path)
    (tmp_path/'api_snapshot.json').write_text(json.dumps({'fetched_at':now().isoformat(),'product_details':{}}))
    (tmp_path/'ai_advice.json').write_text(json.dumps({'status':'ready','headline':'기존 분석'}),encoding='utf-8')
    monkeypatch.setattr(web_sync,'build_snapshot',lambda:{'summary':{}})
    paid=Mock(side_effect=AssertionError('ordinary refresh must not trigger paid generation'))
    monkeypatch.setattr(web_sync,'advice',paid)
    sync=object.__new__(web_sync.Sync);sync.request=Mock();sync.publish=Mock()
    sync.run_job({'id':'test','mode':'quick'})
    paid.assert_not_called()
    assert sync.publish.call_args.args[0]['ai']['headline']=='기존 분석'


def test_period_lookup_falls_back_to_chrome_and_rejects_other_dates(monkeypatch,tmp_path):
    from src import aside_collector
    monkeypatch.setattr(web_sync,'DATA',tmp_path)
    aside=Mock(return_value={'sources':[{'status':'쿠팡윙 로그인 필요'}]})
    monkeypatch.setattr(aside_collector,'collect',aside)
    sync=object.__new__(web_sync.Sync);sync.request=Mock();sync.publish=Mock()
    captured=now().isoformat()
    range_={'start':'2026-11-04','end':'2026-11-07'}
    text='수익 현황\n2026. 11. 01 ~ 2026. 11. 08\n이익\n70\n매출\n100\n비용\n-30\n광고비\n-10\n풀필먼트서비스 비용\n-10\n판매수수료\n-10\n재고 손실 보상\n0'
    source={'kind':'settlement','status':'수집 완료','captured_at':captured,'text':text}
    sync.chrome_period=Mock(return_value={'sources':[source],'received_at':captured})
    job={'id':'period','mode':'profit-period','range':range_}
    sync.run_job(job)
    sync.chrome_period.assert_called_once_with(range_)
    sync.publish.assert_not_called()
    assert sync.request.call_args.kwargs['json']['state']=='failed'
    assert not list(tmp_path.iterdir())
    source['text']=text.replace('2026. 11. 01 ~ 2026. 11. 08','2026. 11. 04 ~ 2026. 11. 07')
    monkeypatch.setattr(web_sync,'build_snapshot',lambda:{'finance':[{**range_,'captured_at':captured}]})
    sync.run_job(job)
    sync.publish.assert_called_once()
    assert sync.request.call_args.kwargs['json']['state']=='complete'
    assert (tmp_path/'browser_snapshot_period_period.json').exists()
    assert not (tmp_path/'browser_snapshot.json').exists()
