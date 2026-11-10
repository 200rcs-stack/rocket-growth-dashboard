"""Validated month-to-date totals from the visible Coupang Ads dashboard."""
import re
from datetime import date
from src.finance import browser_snapshots, kst_timestamp
from config import DATA


def parse_ad_dashboard(text, captured_at, evidence):
    period=re.search(r'조회기간\s+(20\d{2})\.(\d{2})\.(\d{2})\s*~\s*(20\d{2})\.(\d{2})\.(\d{2})',text)
    if not period or '전체 성과 요약' not in text:
        raise ValueError('광고센터 조회기간·성과 요약을 확인할 수 없습니다.')
    first,last=date(*map(int,period.groups()[:3])),date(*map(int,period.groups()[3:]))
    if first>last: raise ValueError('광고센터 조회기간이 잘못됐습니다.')
    def number(label,suffix):
        match=re.search(re.escape(label)+r'\s+([\d,]+(?:\.\d+)?)\s*'+re.escape(suffix),text)
        if not match: raise ValueError(label+' 지표를 확인할 수 없습니다.')
        return float(match.group(1).replace(',',''))
    spend=number('전체 집행 광고비','원')
    sales=number('광고 전환 매출','원')
    roas=number('광고 수익률','%')
    if spend<=0 or sales<0 or roas<0 or abs(sales/spend*100-roas)>0.15:
        raise ValueError('광고센터 지표가 로딩 중이거나 합계가 맞지 않습니다.')
    return {'start':first.isoformat(),'end':last.isoformat(),'spend':int(spend),'sales':int(sales),
            'roas':roas,'captured_at':kst_timestamp(captured_at),'evidence':evidence}


def load_live_ad(data_dir=DATA):
    observations=[]
    for path,payload in browser_snapshots(data_dir):
        for source in payload.get('sources',[]):
            if source.get('kind')!='ad_performance' or source.get('status')!='수집 완료': continue
            try:
                observations.append(parse_ad_dashboard(source['text'],source['captured_at'],str(path)))
            except (ValueError,KeyError,TypeError): continue
    return max(observations,key=lambda row:row['captured_at']) if observations else None
