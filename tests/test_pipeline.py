from datetime import date
from pathlib import Path
import hashlib
import hmac
import pandas as pd
import pytest
from config import RAW
from src.parsers import identifier,parse_inventory,parse_returns,parse_reconciliation
from src.calculator import enrich, strict_total, claims_text
from src.coupang_api import authorization,CoupangReader
from src.compensation import load_compensation, parse_ad_campaigns, attach_compensation
from src.finance import ad_billing, load_finance
from src.settlement_exports import load_settlement_exports

@pytest.mark.parametrize('value,expected',[(95256891745,'95256891745'),('93501960935 (반품-중)','93501960935'),('95256891745.0','95256891745'),('9.5256891745E10','95256891745'),(None,''),('옵션ID 123 잘못된 형식','')])
def test_identifiers(value,expected): assert identifier(value)==expected

def test_actual_inventory():
    df=parse_inventory(RAW/'inventory_health_sku_info_20261023210633.xlsx')
    assert len(df)==43
    assert df.stock_available.sum()==552
    assert df.rev_30d.sum()==390210
    assert df.storage_fee_mtd.isna().sum()==10
    assert strict_total(df.storage_fee_mtd) is None

def test_actual_returns():
    df=parse_returns(RAW/'inventory_health_creturn_v2_info_20261023205302.xlsx',date(2026,10,23))
    assert len(df)==168
    assert df.overdue.sum()==7
    assert df.return_qty.isna().all()
    assert not df.option_id.str.contains(r'\(').any()
    assert '지급 여부' not in claims_text(df) or len(claims_text(df))>100

def test_actual_compensation_and_ad_detail_reconcile():
    compensation, errors = load_compensation()
    campaigns = parse_ad_campaigns(RAW/'cmg_settlement_detail_20261023232642.xlsx')
    assert not errors
    assert len(compensation) == 13
    assert compensation.compensation_amount.sum() == 27780
    assert compensation.period_end.unique().tolist() == ['2026-09-30']
    assert len(campaigns) == 1
    assert campaigns.eligible.sum() == 494757
    returns = parse_returns(RAW/'inventory_health_creturn_v2_info_20261023205302.xlsx',date(2026,10,24))
    joined = attach_compensation(returns, compensation)
    assert len(joined) == len(returns)
    assert joined.compensation_amount.notna().sum() == 13
    assert (joined.overdue & joined.compensation_amount.notna()).sum() == 2


def test_weekly_settlement_exports_preserve_scope_and_vat():
    details, errors = load_settlement_exports()
    assert not errors
    week = [row for row in details if row['period_end'] == '2026-10-04']
    by_part = {row['part']: row for row in week}
    assert by_part['판매수수료']['sales'] == 72100
    assert by_part['판매수수료']['amount'] == 8489
    assert by_part['판매수수료']['rows'] == 12  # Includes signed cancellation rows.
    assert by_part['입출고비']['amount'] == 5335
    assert by_part['배송비']['amount'] == 11055
    assert by_part['보관비']['amount'] == 4536
    assert by_part['반품회수비']['amount'] == 0
    assert by_part['반품재입고비']['amount'] == 0
    assert by_part['반출비']['amount'] == 0
    assert by_part['반출 배송 서비스비 리포트']['amount'] == 0
    assert by_part['바코드 부가 서비스']['amount'] == 0
    assert '리뷰 이벤트' not in by_part  # Empty workbook has no period or total.


def test_browser_observations_use_korean_capture_time():
    bill = ad_billing()
    observations, errors = load_finance()
    assert not errors
    assert bill['captured_at'].endswith('+09:00')
    assert all(row['captured_at'].endswith('+09:00') for row in observations)
    assert bill['eligible'] - bill['promotion'] - bill['adjustment'] + bill['vat'] == bill['bill']
    assert all(row['revenue'] + row['expenses'] + row['compensation'] == row['profit'] for row in observations)

def test_empty_reconciliation_and_historical_signed_values():
    assert parse_reconciliation(RAW/'inventory_reconciliation_report_20261023205311.xlsx').empty
    old=parse_reconciliation(RAW/'inventory_reconciliation_report_20260813094852.xlsx')
    assert len(old)==84
    first=old.iloc[0]
    assert first.outbound==-1
    assert first.returned==1
    assert first.calculated_after==0
    assert first.difference==0

def test_missing_cost_never_turns_into_profit():
    inv=parse_inventory(RAW/'inventory_health_sku_info_20261023210633.xlsx').iloc[3:4].reset_index(drop=True)
    master=pd.DataFrame({'option_id':inv.option_id,'product_name':inv.product_name,'unit_cost':[float('nan')],
          'other_unit_cost':[0.0],'commission_rate':[10.0],'fulfillment_unit':[2000.0],'return_unit':[0.0],'lead_days':[14.0],'target_margin':[20.0]})
    assert enrich(inv,master).contribution_before_unmatched.isna().all()
    master['unit_cost']=0.0
    assert enrich(inv,master).contribution_before_unmatched.notna().all()

def test_hmac_query_encoding():
    signed='261023T120000Z'; path='/test'; query='nextToken=a%2Bb'
    expected=hmac.new(b'secret',(signed+'GET'+path+query).encode(),hashlib.sha256).hexdigest()
    assert authorization('access','secret',path,query,signed).endswith(expected)

def test_api_ip_denial_is_explained_without_leaking_response(monkeypatch):
    class Response:
        status_code=403
        def json(self): return {'message':'Your ip address 192.0.2.10 is not allowed for this request.'}
    monkeypatch.setattr('src.coupang_api.requests.get',lambda *args,**kwargs:Response())
    monkeypatch.setattr('src.coupang_api.time.sleep',lambda *_:None)
    with pytest.raises(RuntimeError,match='공인 IP') as error:
        CoupangReader('A123','access','secret').request('/test',{})
    assert '192.0.2.10' not in str(error.value)

def test_all_pages_and_repeated_token_fail_closed(monkeypatch):
    reader=CoupangReader('A123','access','secret')
    responses=iter([{'data':[{'id':1}],'nextToken':'two'},{'data':[{'id':2}]}])
    monkeypatch.setattr(reader,'request',lambda path,params:next(responses))
    assert reader.pages('/test',{})==[{'id':1},{'id':2}]
    monkeypatch.setattr(reader,'request',lambda path,params:{'data':[],'nextToken':'same'})
    with pytest.raises(RuntimeError,match='토큰 반복'): reader.pages('/test',{})

def test_streamlit_all_pages():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    assert not app.exception
    for page in ['상품별 손익','재고·입고','반품·보상 확인','원가 설정','자료실·연결','한눈에 보기']:
        app.sidebar.radio[0].set_value(page).run(timeout=30)
        assert not app.exception, f'{page}: {app.exception}'
    app.sidebar.text_input[0].set_value('존재하지않는상품_테스트').run(timeout=30)
    assert not app.exception
