"""Period-aligned Wing observations; never combine these with rolling SKU sales."""
import calendar
import json
import re
from datetime import date, datetime
from config import DATA, KST


def kst_timestamp(value):
    """Compare browser UTC and local file observations on one clock."""
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(KST).isoformat()


def browser_snapshots(data_dir):
    """Retain the most recent valid observation when a later collection fails."""
    paths=[*sorted(data_dir.glob('browser_snapshot_*.json')),data_dir/'browser_snapshot.json']
    for path in paths:
        if path.exists():
            try:
                yield path,json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,UnicodeError):
                continue


def parse_settlement(text, captured_at, evidence):
    if '수익 현황' not in text:
        raise ValueError('수익 현황 화면이 아닙니다.')
    section=text.split('수익 현황',1)[1].split('다가오는 정산',1)[0]
    # Accept both an accessibility snapshot and rendered innerText.
    clean=[]
    for line in section.splitlines():
        line=re.sub(r'^\s*-\s*(?:text|generic|definition|term|button|paragraph)(?:\s+"[^"]*")?:\s*','',line).strip()
        line=line.strip('"')
        if line: clean.append(line)
    normalized='\n'.join(clean)
    period=re.search(r'(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*~\s*(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})',normalized)
    if not period: raise ValueError('조회 기간을 확인할 수 없습니다.')
    nums=list(map(int,period.groups()))
    start,end=date(*nums[:3]),date(*nums[3:])
    if end<start: raise ValueError('조회 기간이 잘못되었습니다.')
    def amount(label,optional=False):
        for i,line in enumerate(clean):
            if line==label:
                for candidate in clean[i+1:i+7]:
                    if re.fullmatch(r'[+-]?\s*\d[\d,]*',candidate):
                        return int(candidate.replace(',','').replace(' ',''))
        if optional: return None
        raise ValueError(label+' 금액을 확인할 수 없습니다.')
    values={key:amount(label) for key,label in {'profit':'이익','revenue':'매출','expenses':'비용','ads':'광고비','fulfillment':'풀필먼트서비스 비용','commission':'판매수수료','compensation':'재고 손실 보상'}.items()}
    if values['revenue']+values['expenses']+values['compensation']!=values['profit']:
        raise ValueError('수익 합계가 맞지 않아 반영하지 않았습니다.')
    if values['ads']+values['fulfillment']+values['commission']!=values['expenses']:
        raise ValueError('비용 합계가 맞지 않아 반영하지 않았습니다.')
    last_day=calendar.monthrange(end.year,end.month)[1]
    return {**values,'start':start.isoformat(),'end':end.isoformat(),'captured_at':kst_timestamp(captured_at),
            'evidence':evidence,'source_url':'https://wing.coupang.com/tenants/rfm/settlements/home',
            'complete_month':start.day==1 and start.year==end.year and start.month==end.month and end.day==last_day,
            'shipping':amount('배송비',True),'handling':amount('입출고비',True),
            'storage':amount('보관비',True),'fulfillment_vat':amount('부가가치세',True)}


def load_finance(data_dir=DATA):
    observations=[]; errors=[]
    for path in (data_dir/'evidence').glob('settlement_20*.txt'):
        try:
            captured=datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
            observations.append(parse_settlement(path.read_text(encoding='utf-8'),captured,str(path)))
        except ValueError as ex: errors.append(path.name+': '+str(ex))
    for path,payload in browser_snapshots(data_dir):
        try:
            for source in payload.get('sources',[]):
                if source.get('kind')=='settlement' and source.get('status')=='수집 완료':
                    row=parse_settlement(source['text'],source.get('captured_at',payload['received_at']),str(path))
                    if source.get('period_query'):row['period_query']=True
                    observations.append(row)
        except (ValueError,KeyError,TypeError) as ex: errors.append('브라우저 정산 자료: '+str(ex))
    latest={}
    normal_ranges={(r['start'],r['end']) for r in observations if not r.get('period_query')}
    for row in sorted(observations,key=lambda r:r['captured_at']):
        key=(row['start'],row['end'])
        latest[key]={**row,'period_query':key not in normal_ranges}
    # For the same end date, show the wider month-to-date period before a
    # shorter seven-day view so the landing page reflects the business month.
    return sorted(latest.values(),key=lambda r:(not r['period_query'],r['end'],-date.fromisoformat(r['start']).toordinal()),reverse=True),errors


def settlement_schedule(data_dir=DATA):
    path=data_dir/'evidence/settlement_schedule_details.txt'
    if not path.exists(): return []
    pattern=r'^\s+- row "(20\d{2}-\d{2}-\d{2}) (주별|월별) (\d+) (20\d{2}-\d{2}-\d{2}~20\d{2}-\d{2}-\d{2}) ([\d,]+) 상세보기'
    rows=[]; seen=set()
    for date_paid,kind,ratio,sale_range,payout in re.findall(pattern,path.read_text(encoding='utf-8'),re.M):
        row=(date_paid,kind,int(ratio),sale_range,int(payout.replace(',','')))
        if row not in seen: seen.add(row); rows.append(row)
    return rows


def ad_billing(data_dir=DATA):
    observations=[]
    def parse(text,evidence,captured_at):
        match=re.search(r'(20\d{2})년\s*(\d{1,2})월\s+([\d,]+)원\s+([\d,]+)원\s+([\d,]+)원\s+([\d,]+)원\s+([\d,]+)원',text)
        if not match: return
        year,month,*amounts=match.groups()
        eligible,promo,adjustment,vat,bill=(int(n.replace(',','')) for n in amounts)
        if eligible-promo-adjustment+vat!=bill: return
        observations.append({'month':f'{year}-{int(month):02d}','eligible':eligible,'promotion':promo,
                             'adjustment':adjustment,'vat':vat,'bill':bill,'evidence':evidence,'captured_at':kst_timestamp(captured_at)})
    for path in (data_dir/'evidence').glob('ad_billing_*.txt'):
        parse(path.read_text(encoding='utf-8'),str(path),datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat())
    for path,payload in browser_snapshots(data_dir):
        try:
            for source in payload.get('sources',[]):
                if source.get('kind')=='ad_billing' and source.get('status','').startswith(('수집 완료','화면 수집 완료')):
                    parse(source.get('text',''),str(path),source.get('captured_at',payload.get('received_at','')))
        except (ValueError,KeyError,TypeError): pass
    return max(observations,key=lambda row:row['captured_at']) if observations else None


def ad_campaign_screen(data_dir=DATA):
    """Read campaign rows visible on Wing's current ad-billing page only."""
    observations=[]
    for path,payload in browser_snapshots(data_dir):
        for source in payload.get('sources',[]):
            if source.get('kind')!='ad_billing' or not source.get('status','').startswith(('수집 완료','화면 수집 완료')):
                continue
            content=source.get('text','')
            if '상세내역' not in content: continue
            rows=[]
            for line in content.split('상세내역',1)[1].splitlines():
                cells=[cell.strip() for cell in line.split('\t')]
                if len(cells)!=7 or not cells[0].isdigit(): continue
                try:
                    amount=lambda value:int(value.replace(',','').replace('원','').strip())
                    rows.append({'번호':int(cells[0]),'광고유형':cells[1],'캠페인':cells[2],
                                 '노출수':cells[3],'클릭수':cells[4],
                                 '광고비(원)':amount(cells[5]),'청구가능 광고비(원)':amount(cells[6])})
                except ValueError: continue
            if rows:
                observations.append({'rows':rows,'captured_at':kst_timestamp(source.get('captured_at',payload.get('received_at',''))),
                                     'evidence':str(path)})
    return max(observations,key=lambda row:row['captured_at']) if observations else None
