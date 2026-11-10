from datetime import datetime,timedelta
from config import KST
from src.operating_manual import source_health, master_manual

def test_fresh_time_does_not_override_collection_failure():
    at=datetime(2026,10,27,12,tzinfo=KST)
    health=source_health({'time':at.isoformat(),'status':'쿠팡윙 본문 로딩 실패'},at)
    assert health['freshness']=='최근 수집' and health['review_required']
    assert source_health({'time':(at+timedelta(hours=1)).isoformat(),'status':'검증됨'},at)['review_required']
    assert source_health({'time':None,'status':'검증됨'},at)['review_required']
    assert source_health({'time':(at-timedelta(hours=3)).isoformat(),'status':'검증됨'},at)['review_required']
    assert not source_health({'time':at.isoformat(),'status':'검증됨'},at)['review_required']

def test_missing_manual_source_remains_blocked_even_when_checks_are_done():
    snap={'summary':{'missing_costs':1,'restock':2,'overdue_returns':3},'sources':[], 'generated_at':'test'}
    manual=master_manual(snap)
    assert len(manual['sections'])==6
    assert all(x['source_review_required'] for x in manual['sections'])
    assert all(x['steps'] and x['stop_conditions'] and x['completion'] for x in manual['sections'])
