"""Explicit, customer-PII-free projection for the private web dashboard and AI."""
import json
import hashlib
from pathlib import Path
import pandas as pd
from config import DATA, RAW, KST, now
from datetime import datetime
from src.file_loader import load_data, digest
from src.calculator import enrich, master_for, strict_total
from src.finance import load_finance, ad_billing
from src.ad_live import load_live_ad
from src.settlement_exports import load_settlement_exports
from src.ad_performance import load_ad_performance
from src.compensation import load_compensation, load_ad_campaigns
from src.returns_insights import latest_return_insight
from src.operating_manual import source_health, master_manual
from src.revenue_comparison import compare_revenue
from src.product_prices import price_rows
from src.operations_chat import sales_windows


def records(df):
    return json.loads(df.to_json(orient='records', date_format='iso', force_ascii=False))


def safe_observation(row):
    return {k: v for k, v in row.items() if k not in ('evidence', 'source_url')} if row else None


def explicit_kst(value):
    if not value: return value
    date=datetime.fromisoformat(value.replace('Z','+00:00'))
    if date.tzinfo is None: date=date.replace(tzinfo=KST)
    return date.astimezone(KST).isoformat()


def build_snapshot():
    data = load_data()
    inv = data['inventory']
    enriched = enrich(inv, master_for(inv)) if not inv.empty else inv
    api_path = DATA / 'api_snapshot.json'
    api = json.loads(api_path.read_text(encoding='utf-8')) if api_path.exists() else {}
    finance, finance_errors = load_finance()
    ledger, ledger_errors = load_settlement_exports()
    ad_detail, ad_path, ad_errors = load_ad_performance()
    comp, comp_errors = load_compensation()
    campaigns, campaign_errors = load_ad_campaigns()
    ad_product=[];ad_daily=[]
    if not ad_detail.empty:
        measures=['impressions','clicks','spend','orders_14d','sales_14d']
        grouped=ad_detail.groupby(['option_id','product'],dropna=False)[measures].sum().reset_index()
        grouped['roas']=grouped.sales_14d/grouped.spend.where(grouped.spend.gt(0))*100
        ad_product=records(grouped.sort_values('spend',ascending=False))
        ad_daily=records(ad_detail.groupby('date')[measures].sum().reset_index())
    files = [{**f, 'time':explicit_kst(f['time']), 'id': digest(RAW / f['name'])} for f in data['files']]
    inventory = records(enriched) if not enriched.empty else []
    returns = records(data['returns'][['request_date', 'product_name', 'option_id', 'reason', 'process_status', 'elapsed_days', 'overdue', 'return_qty', 'source_file']]) if not data['returns'].empty else []
    # Order-level identifiers and customer information never enter the web/AI projection.
    daily = {}
    for order in api.get('orders', []):
        date = pd.Timestamp(order['paidAt'], unit='ms', tz='UTC').tz_convert('Asia/Seoul').date().isoformat()
        row = daily.setdefault(date, {'date': date, 'revenue': 0, 'quantity': 0, 'orders': 0})
        row['orders'] += 1
        for item in order['orderItems']:
            row['quantity'] += item['salesQuantity']
            row['revenue'] += float(item['unitSalesPrice']) * item['salesQuantity']
    if api.get('paid_from'):
        for day in pd.date_range(api['paid_from'], api['paid_to']):
            date = day.date().isoformat()
            daily.setdefault(date, {'date': date, 'revenue': 0, 'quantity': 0, 'orders': 0})
    api_inventory = [{'option_id': str(x['vendorItemId']), 'stock': x['inventoryDetails']['totalOrderableQuantity']} for x in api.get('inventory', [])]
    prices=price_rows(api)
    for row in prices:
        paid=row.pop('latest_order_paid_ms')
        row['latest_order_paid_at']=datetime.fromtimestamp(paid/1000,tz=KST).isoformat() if paid is not None else None
    current_prices=[row for row in prices if row['sale_price'] is not None and not row['retained']]
    option_sales=sales_windows(api,{row['option_id'] for row in prices+api_inventory})
    price_errors=api.get('product_price_errors',0)
    browser = {}
    path = DATA / 'browser_snapshot.json'
    if path.exists():
        browser = json.loads(path.read_text(encoding='utf-8'))
    screen_status = {s['kind']: {'status': s['status'], 'time': s.get('captured_at')} for s in browser.get('sources', [])}
    return_insight = latest_return_insight()
    sources = [
        {'id':'api_inventory','name':'공식 API · 재고','scope':'전체 조회 옵션의 판매가능재고','time':api.get('fetched_at'),'count':len(api_inventory),'method':'API','status':'연결됨' if api else '미수집'},
        {'id':'api_orders','name':'공식 API · 주문','scope':f"{api.get('paid_from','—')} ~ {api.get('paid_to','—')} · 출고일 이후 지원 주문. 취소·환불 차감 전",'time':api.get('fetched_at'),'count':len(api.get('orders',[])),'method':'API','status':'연결됨' if api else '미수집'},
        {'id':'api_products','name':'공식 API · 상품','scope':'로켓그로스 및 혼합 운영 등록상품','time':api.get('fetched_at'),'count':len(api.get('products',[])),'method':'API','status':'연결됨' if api else '미수집'},
        {'id':'api_prices','name':'공식 API · 옵션 판매가','scope':'로켓그로스 상품 상세의 옵션별 등록 판매가 · 주문 단가와 구분','time':max((row['captured_at'] for row in current_prices),default=None),'count':len(current_prices),'method':'API','status':f'상품 상세 {price_errors}건 갱신 실패' if price_errors else ('검증됨' if current_prices else '미수집')},
        {'id':'inventory','name':'재고 현황 엑셀','scope':'상품·옵션·등급별 재고 및 지난 7일·30일 판매. 최근 매출은 원본 기준 번들 매출 제외','time':data.get('inventory_time'),'count':len(inventory),'method':'Excel','status':'검증됨' if inventory else '미수집'},
        {'id':'returns','name':'고객 반품 엑셀','scope':'원본에 포함된 접수 건. 판매 모수와 기간이 달라 반품률로 환산하지 않음','time':data.get('returns_time'),'count':len(returns),'method':'Excel','status':'검증됨' if returns else '미수집'},
        {'id':'finance','name':'윙 수익 현황','scope':'화면 조회기간별 매출·비용. 매입원가 차감 전','time':finance[0]['captured_at'] if finance else None,'count':len(finance),'method':'브라우저','status':screen_status.get('settlement',{}).get('status','과거 자료')},
        {'id':'ads','name':'광고센터 성과','scope':'화면 조회기간의 집행비·광고 전환매출. 전체 매출과 중복 합산 금지','time':(load_live_ad() or {}).get('captured_at'),'count':1 if load_live_ad() else 0,'method':'브라우저','status':screen_status.get('ad_performance',{}).get('status','과거 자료')},
        {'id':'settlement','name':'정산 상세 엑셀','scope':'정산주기별 수수료·배송·보관·반품·반출 비용','time':max((f['time'] for f in files if f['kind']=='settlement_detail'),default=None),'count':len(ledger),'method':'Excel','status':'과거 원본 · 필요 시 갱신'},
    ]
    for ident, screen in [('inventory','inventory'),('returns','inventory')]:
        last_status=screen_status.get(screen,{}).get('status')
        if last_status and last_status!='수집 완료':
            next(x for x in sources if x['id']==ident)['status']=last_status+' · 이전 원본 유지'
    sources.append({'id':'return_insight','name':'윙 고객반품 분석','scope':'윙이 표시한 월별 반품률. 반품 엑셀 접수 건수와 별도 지표',
                    'time':return_insight['captured_at'] if return_insight else None,
                    'count':return_insight.get('products') if return_insight else None,'method':'브라우저',
                    'status':screen_status.get('customer_returns',{}).get('status','과거 자료' if return_insight else '미수집')})
    download_by_id={'inventory':'inventory_health_sku_info_', 'returns':'inventory_health_creturn_v2_info_'}
    inv_screen=next((x for x in browser.get('sources',[]) if x['kind']=='inventory'),{})
    if inv_screen.get('status')=='수집 완료' and 'downloads' in inv_screen:
        for ident,prefix in download_by_id.items():
            if not any((x.startswith(prefix) if isinstance(x,str) else (x.get('status')=='파일 저장 완료' and x.get('name','').startswith(prefix))) for x in inv_screen['downloads']):
                next(x for x in sources if x['id']==ident)['status']='엑셀 다운로드 미완료 · 이전 원본 유지'
    for ident,label,kind,count,scope in [
        ('ad_detail','광고 일별·상품별 성과 엑셀','ad_performance',len(ad_detail),'보관된 광고 보고서의 14일 기여 전환. 최신 광고 요약과 별도 기간'),
        ('compensation','재고 손실 보상 엑셀','compensation',len(comp),'원본에 포함된 보상 내역. 반품 전체의 미보상 여부를 확정하지 않음'),
        ('reconciliation','재고 변동 엑셀','reconciliation',len(data['reconciliation']),'부호 있는 재고 이동 합계와 기말재고 대조')]:
        matching=[f for f in files if f['kind']==kind and f['active']]
        sources.append({'id':ident,'name':label,'scope':scope,'time':matching[0]['time'] if matching else None,'count':count,'method':'Excel','status':'보관 원본 검증됨' if matching else '미수집'})
    gaps = [
        {'name':'문의·리뷰 본문 / 판매자 점수','reason':'수집 연결 및 원본 검증이 아직 없습니다.'},
        {'name':'미출고·취소·환불 전체 내역','reason':'현재 주문 API 범위에 포함되지 않습니다.'},
        {'name':'입고 예약·반출 신청 전체','reason':'재고 엑셀의 수량만 확보했습니다. 상세 절차 자료는 미연결입니다.'},
        {'name':'광고 캠페인·키워드의 최신 상세 성과','reason':'월 누적 요약과 기존 상세 원본만 확보했습니다.'},
        {'name':'정산의 최신 전체 기간','reason':'보관된 기간만 확인 가능합니다. 화면 수집 실패 시 과거 자료를 유지합니다.'},
        {'name':'확정 순이익','reason':'상품 매입원가·기타 비용·동일 기간 환불과 정산 대조가 필요합니다.'},
    ]
    # Explicitly surface failed page updates with the time of the retained data.
    for kind,label in [('settlement','정산 화면의 최신 수익'),('customer_returns','고객반품 분석의 최신 반품률')]:
        status=screen_status.get(kind,{}).get('status')
        if status and status!='수집 완료':
            gaps.insert(0,{'name':label,'reason':status+'. 원본이 갱신되기 전까지 마지막 검증 자료만 표시합니다.'})
    summary = {'revenue30':strict_total(inv.rev_30d) if len(inv) else None,
               'sold30':strict_total(inv.qty_30d) if len(inv) else None,
               'api_stock':sum(x['stock'] for x in api_inventory) if api else None,
               'inventory_stock':strict_total(inv.stock_available) if len(inv) else None,
               'out_of_stock':int(enriched.out_of_stock.sum()) if len(inv) else None,
               'restock':int(enriched.restock_alert.sum()) if len(inv) else None,
               'return_cases':len(returns) if data.get('returns_time') else None, 'overdue_returns':sum(bool(x['overdue']) for x in returns) if data.get('returns_time') else None,
               'missing_costs':int(enriched.unit_cost.isna().sum()) if len(inv) else None}
    result = {'schema':1,'generated_at':now().isoformat(),'summary':summary,'inventory':inventory,
              'api_inventory':api_inventory,'product_prices':prices,'option_sales_windows':option_sales,
              'option_names':data.get('option_names',{}),
              'returns':returns,'daily':sorted(daily.values(),key=lambda x:x['date']),
              'products':[{k:p.get(k) for k in ('sellerProductId','sellerProductName','brand','statusName','saleStartedAt','saleEndedAt')} | {'options':len(p.get('items',[]))} for p in api.get('products',[])],
              'finance':[safe_observation(x) for x in finance], 'ads':safe_observation(load_live_ad()),
              'billing':safe_observation(ad_billing()),'ledger':ledger,'files':files,'sources':sources,'gaps':gaps,
              'ad_products':ad_product,'ad_daily':ad_daily,
              'ad_period':{'start':ad_detail.date.min().date().isoformat(),'end':ad_detail.date.max().date().isoformat(),'source_file':ad_path.name} if ad_path else None,
              'campaigns':records(campaigns),
              'compensation':records(comp.drop(columns=['order_no','inspection_no'],errors='ignore')),
              'reconciliation':records(data['reconciliation']),'reconciliation_period':data['reconciliation'].attrs.get('period'),
              'return_insight':safe_observation(return_insight),
              'revenue_comparison':compare_revenue(inventory,api),
              'errors':data['errors']+finance_errors+ledger_errors+ad_errors+comp_errors+campaign_errors}
    # A separately labelled historical query tests the one-day boundary
    # hypothesis. Only compare it to the exact inventory file used in that audit.
    checks=[]
    for audit_path in sorted(DATA.glob('revenue_period_audit_*.json')):
        audit=json.loads(audit_path.read_text(encoding='utf-8'))
        if not inventory or audit.get('inventory_source_file')!=inventory[0].get('source_file'): continue
        check=compare_revenue(inventory,audit)
        checks.append({k:check[k] for k in ('api_start','api_end','api_amount','matched_api_amount','unmatched_api_amount','remaining_difference','api_order_count')}
                      | {'captured_at':audit.get('fetched_at'),'inventory_source_file':audit['inventory_source_file'],'meaning':'기간을 하루 앞당긴 검증용 조회. 엑셀 원본의 정확한 기간을 확인했다는 뜻은 아님.'})
    result['revenue_comparison']['period_checks']=checks
    if checks:
        sources.append({'id':'api_order_period_check','name':'API · 판매금액 기간 대조','scope':'원본 재고 파일을 고정하고 결제일 범위를 하루 앞당긴 비교 조회. 엑셀의 정확한 기간은 미확인.',
                        'time':checks[-1]['captured_at'],'count':checks[-1]['api_order_count'],'method':'API','status':'검증용 조회 보관'})
    for source in sources:
        source['time']=explicit_kst(source['time'])
        source['quality']=source_health(source)
    result['manual']=master_manual(result)
    result['quality']={'review_required':sum(s['quality']['review_required'] for s in sources),
                       'total_sources':len(sources),'uncollected_scopes':len(gaps),
                       'rules_version':'2026.10.27-v1'}
    # JSON round trip rejects NaN and catches accidental unsupported types.
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def ai_facts(snapshot):
    return {k:snapshot[k] for k in ('summary','sources','gaps','ads')} | {
        'finance_latest_only':snapshot['finance'][:1],
        'input_cost_analysis':{k:(snapshot.get('cost_analysis') or {}).get(k) for k in ('total','entered','matched','full','stock_full','cogs','gross','margin','stock_cost','stock_covered','inbound_cost','long_stock_cost','restock_cost','note')},
        'period_profit_inputs':{k:(snapshot.get('profit') or {}).get(k) for k in ('start','end','cogs','extra','net_profit','confirmed','missing')},
        'units_and_limits':{'return_cases':'반품 접수 건수. 수량(개)이 아님. 폐기 예정도 건수로만 표기.', 'revenue30':'재고 엑셀 SKU 범위 최근 30일 판매금액. 광고/정산 자료와 기간·범위가 달라 직접 비교 금지.', 'missing_costs':'원가 미입력 SKU 행 수. 순이익·적자 원인·손익분기 ROAS 확정 불가.', 'restock':'입고 검토 SKU 행 수, 발주 확정 아님.'},
        'inventory':[{k:r.get(k) for k in ('option_id','product_name','stock_available','qty_30d','rev_30d','doc_days','restock_rec_qty','stock_status','unit_cost','cost_origin','cost_sales_confirmed')} for r in snapshot['inventory']],
        'return_status_counts':pd.Series([r['process_status'] for r in snapshot['returns']],dtype='string').value_counts().to_dict()}
