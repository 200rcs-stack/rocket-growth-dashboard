import pytest
from src.ad_live import parse_ad_dashboard


def test_ads_dashboard_waits_for_loaded_values_and_checks_roas():
    text='조회기간 2026.10.01 ~ 2026.10.23\n전체 성과 요약\n전체 집행 광고비\n521,015\n원\n광고 전환 매출\n683,100\n원\n광고 수익률\n131.11\n%'
    result=parse_ad_dashboard(text,'2026-10-24T14:40:00Z','screen.json')
    assert (result['start'],result['end'],result['spend'],result['sales'])==('2026-10-01','2026-10-23',521015,683100)
    with pytest.raises(ValueError,match='로딩 중'):
        parse_ad_dashboard(text.replace('521,015','0'),'2026-10-24T14:40:00Z','screen.json')
