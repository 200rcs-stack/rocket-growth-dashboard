"""Read-only operational answers from the dashboard's verified sources."""
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from config import KST, now
from src.product_prices import names, normalized, requested_ids


def iso_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def sales_windows(api, option_ids):
    first, last, fetched = (iso_date(api.get(key)) for key in ('paid_from', 'paid_to', 'fetched_at'))
    if not all((first, last, fetched)):
        return None
    end=min(last,fetched-timedelta(days=1))
    start=end-timedelta(days=13)
    if first>start:
        return None
    split=start+timedelta(days=7)
    recent, earlier=Counter(),Counter()
    seen={}
    for order in api.get('orders',[]):
        paid=datetime.fromtimestamp(order['paidAt']/1000,tz=KST).date()
        if not start<=paid<=end:
            continue
        totals=Counter()
        for item in order['orderItems']:
            totals[str(item['vendorItemId'])]+=item['salesQuantity']
        order_id=str(order['orderId'])
        if order_id in seen:
            if seen[order_id]!=(paid,totals): return None
            continue
        seen[order_id]=(paid,totals)
        (recent if paid>=split else earlier).update(totals)
    return {'recent_start':split.isoformat(),'recent_end':end.isoformat(),
            'previous_start':start.isoformat(),'previous_end':(split-timedelta(days=1)).isoformat(),
            'options':[{'option_id':ident,'recent_qty':recent[ident],'previous_qty':earlier[ident]}
                       for ident in sorted(set(option_ids)|recent.keys()|earlier.keys())]}


def operations_rows(snapshot):
    inventory=defaultdict(list)
    for row in snapshot.get('inventory',[]):
        inventory[str(row['option_id'])].append(row)
    prices={row['option_id']:row for row in snapshot.get('product_prices',[])}
    stock={row['option_id']:row['stock'] for row in snapshot.get('api_inventory',[])}
    sales={row['option_id']:row for row in (snapshot.get('option_sales_windows') or {}).get('options',[])}
    historical=snapshot.get('option_names') or {}
    fallback={}
    for row in snapshot.get('compensation',[]):
        oid=str(row.get('option_id') or '')
        if oid and row.get('product_name'):
            fallback.setdefault(oid,{'product_name':row['product_name'],'option_name':row.get('option_name') or '','origin':'재고 손실 보상 원본'})
    for row in snapshot.get('reconciliation',[]):
        oid=str(row.get('option_id') or '')
        raw_name=str(row.get('product_name') or '').strip()
        if oid and raw_name:
            parts=[x.strip() for x in raw_name.rsplit(',',1)]
            fallback.setdefault(oid,{'product_name':parts[0],'option_name':parts[1] if len(parts)>1 else '','origin':'재고 변동 원본'})
    for row in snapshot.get('ad_products',[]):
        oid=str(row.get('option_id') or '')
        raw_name=str(row.get('product') or '').strip()
        if oid and raw_name:
            parts=[x.strip() for x in raw_name.rsplit(',',1)]
            fallback.setdefault(oid,{'product_name':parts[0],'option_name':parts[1] if len(parts)>1 else '','origin':'광고 성과 원본'})
    for row in snapshot.get('returns',[]):
        oid=str(row.get('option_id') or '')
        raw_name=str(row.get('product_name') or '').strip()
        if oid and raw_name:
            parts=[x.strip() for x in raw_name.rsplit(',',1)]
            fallback.setdefault(oid,{'product_name':parts[0],'option_name':parts[1] if len(parts)>1 else '','origin':'고객 반품 원본'})
    raw_rows=[]
    for ident in sorted(prices.keys()|inventory.keys()|stock.keys()|sales.keys()):
        price=prices.get(ident,{})
        wing=inventory[ident]
        hist=historical.get(ident) or fallback.get(ident) or {}
        reference=price or (wing[0] if wing else hist)
        wing_avail=[w.get('stock_available') for w in wing if w.get('stock_available') is not None]
        raw_rows.append({'option_id':ident,'product_id':price.get('product_id') or (wing[0].get('product_id') if wing else hist.get('product_id')),
               'product_name':reference.get('product_name') or '등록상품명 미확인',
               'option_name':reference.get('option_name') or '옵션명 미확인','aliases':names(price),
               'name_origin':hist.get('origin') if not price and not wing and hist else None,
               'historical_grade':hist.get('grade') if not price and not wing and hist else None,
               'active_listing':bool(price or wing),
               'units_per_option':price.get('units_per_option'),
               'price':price.get('sale_price'),'latest_order_price':price.get('latest_order_price'),'price_time':price.get('captured_at'),
               'api_stock':stock.get(ident),'wing_stock':sum(wing_avail) if wing_avail else None,
               'wing':wing,'recent_qty':sales.get(ident,{}).get('recent_qty'),'previous_qty':sales.get(ident,{}).get('previous_qty')})
    by_family=defaultdict(list)
    for r in raw_rows:
        by_family[r['product_id'] or r['product_name']].append(r)
    for r in raw_rows:
        if r['api_stock'] is None:
            base_key=_strip_pack(r['option_name'])
            siblings=[s for s in by_family[r['product_id'] or r['product_name']] if s['api_stock'] is not None and _strip_pack(s['option_name'])==base_key and _pack_units(s)==1]
            if not siblings:
                siblings=[s for s in by_family[r['product_id'] or r['product_name']] if s['api_stock'] is not None and _strip_pack(s['option_name'])==base_key]
            if siblings:
                base=siblings[0]
                pack_qty=_pack_units(r)
                r['api_stock']=base['api_stock']//pack_qty
                r['bundle_base_option']=base['option_name']
                r['bundle_base_id']=base['option_id']
                r['bundle_base_stock']=base['api_stock']
                r['bundle_units']=pack_qty
                r['bundle_base_inbound']=sum((w.get('stock_inbound') or 0) for w in base['wing']) if base['wing'] else None
                if r['units_per_option'] in (None,1) and pack_qty>1:
                    r['units_per_option']=pack_qty
        yield r


def _strip_pack(name):
    return re.sub(r'(?<!\d)\d+\s*(?:개(?!입)|박스|세트|팩|통|병|장|매|롤|포|봉|구|p|정(?!\s*$)|캡슐)','',str(name or ''),flags=re.I).strip()


def _pack_units(row):
    matches=re.findall(r'(?<!\d)(\d+)\s*(?:개(?!입)|박스|세트|팩)',str(row.get('option_name') or ''),flags=re.I)
    if matches:
        return max(1,int(matches[-1]))
    return max(1,int(row.get('units_per_option') or 1))


def _stock_desc(row, *, short=False):
    if row.get('bundle_base_option'):
        base_opt=row['bundle_base_option']
        base_st=row['bundle_base_stock']
        sets=row['api_stock']
        if sets==0:
            return f"0세트 (모체 '{base_opt}' 재고 {base_st:g}개 공유 · 품절)" if short else f"API 재고 0개 · 묶음품절(모체 '{base_opt}' 단품재고 {base_st:g}개 공유)"
        return f"{sets:g}세트 가능 (모체 '{base_opt}' 단품 {base_st:g}개 공유)" if short else f"API 재고 {sets:g}세트 가능(모체 '{base_opt}' 단품재고 {base_st:g}개 공유)"
    if row.get('api_stock') is not None:
        if row['api_stock']==0:
            return '0개' if short else 'API 재고 0개 · 품절 영향 확인'
        return f"{row['api_stock']:g}개" if short else f"API 재고 {row['api_stock']:g}개"
    if row.get('wing_stock') is not None:
        return f"Wing {row['wing_stock']:g}개" if short else f"Wing 재고 {row['wing_stock']:g}개"
    return '미확인' if short else '재고 미확인'


_KOR_PACKS = {'한개':'1개','두개':'2개','세개':'3개','네개':'4개','다섯개':'5개','단품':'1개','단일':'1개'}


def _option_tokens(text):
    clean=normalized(text)
    for k,v in _KOR_PACKS.items():
        clean=clean.replace(k,v)
    tokens=set(re.findall(r'\d+개|\d+ml|\d+l|\d+g|\d+kg|\d+p|\d+정|\d+캡슐|\d+박스|[가-힣]{2,}|[a-z]{2,}',str(text or '').casefold()))
    for k,v in _KOR_PACKS.items():
        if k in clean: tokens.add(v)
    return tokens-{'옵션','상품','제품','기준','정리','추천','사이즈','타입'}


def _prefer_active(rows, question):
    if re.search(r'반품|등급|이전|과거|전체\s*ID',question):
        return rows
    active=[r for r in rows if r.get('active_listing') or (r.get('api_stock') or 0)>0 or (r.get('recent_qty') or 0)>0 or (r.get('previous_qty') or 0)>0]
    if active and len(active)<len(rows):
        primary=[r for r in active if r.get('active_listing')]
        return primary or active
    return rows


def product_matches(rows,question):
    ids=requested_ids(question)
    if ids: return [row for row in rows if row['option_id'] in ids or row['product_id'] in ids]
    query=normalized(question)
    for k,v in _KOR_PACKS.items():
        query=query.replace(k,v)
    candidates={}
    for row in rows:
        aliases=[row['product_name'],*row['aliases']]
        full=max((len(normalized(name)) for name in aliases if len(normalized(name))>=3 and normalized(name) in query),default=0)
        if not full:
            # Use meaningful title words for short questions such as “생존침낭 재고 있어?”
            tokens={token for name in aliases for token in re.findall(r'[가-힣a-zA-Z0-9]{2,}',name) if len(normalized(token))>=2}
            tokens-={'마인더리','로켓그로스','휴대용','가정용','추천','데일리','1세트','국내배송','여행용','캠핑용','초소형','다용도','일체형','고급형','상품','옵션','제품','기준','전체','우리'}
            matched_tokens=[normalized(token) for token in tokens if len(normalized(token))>=2 and normalized(token) in query]
            if matched_tokens:
                # Score by sum of matched distinct token lengths so multi-word queries rank the best product family highest
                full=sum(len(t) for t in set(matched_tokens))
        if full: candidates[row['option_id']]=full
    if not candidates: return []
    best=max(candidates.values())
    families={row['product_id'] or normalized(row['product_name']) for row in rows if candidates.get(row['option_id'])==best}
    matched=[row for row in rows if (row['product_id'] or normalized(row['product_name'])) in families]
    variants=[row for row in matched if len(normalized(row['option_name']))>=3 and normalized(row['option_name']) in query]
    if variants: return _prefer_active(variants,question)
    # Token-level option matching handles word-order reversals like “녹색 1개” vs “1개 녹색”
    scored=[]
    for row in matched:
        opt_tokens=_option_tokens(row['option_name'])
        hits=[tok for tok in opt_tokens if normalized(tok) in query]
        if hits:
            scored.append((len(hits),sum(len(normalized(t)) for t in hits),row))
    if scored:
        top_count=max(x[0] for x in scored)
        top_len=max(x[1] for x in scored if x[0]==top_count)
        return _prefer_active([x[2] for x in scored if x[0]==top_count and x[1]==top_len],question)
    return _prefer_active(matched,question)


def option_fact(row):
    fields={'상품':row['product_name'],'옵션':row['option_name'],'옵션 ID':row['option_id'],
            'API 판매가능재고(개)':row['api_stock'],'등록 판매가(원)':row['price'],'가격 조회 시각':row['price_time'],
            '최근 7일 API 주문수량(옵션 단위)':row['recent_qty'],'직전 7일 API 주문수량(옵션 단위)':row['previous_qty']}
    if row.get('units_per_option') is not None:
        fields['옵션 구성 수량(개)']=row['units_per_option']
    if row.get('bundle_base_option'):
        fields['묶음재고 연동 기준']=f"모체 옵션({row['bundle_base_option']} · ID {row['bundle_base_id']}) 단품재고 {row['bundle_base_stock']:g}개 공유 ({row['bundle_units']}개 묶음)"
    if row.get('name_origin'):
        fields['명칭 확인 출처']=row['name_origin']
    if row.get('historical_grade'):
        fields['이전 확인 등급']=row['historical_grade']
    for item in row['wing']:
        grade=item.get('grade') or '등급 미확인'
        fields[f'{grade} · Wing 재고 / 입고예정 / 권장수량 / 권장일']={
            '판매가능':item.get('stock_available'),'입고예정':item.get('stock_inbound'),
            '권장수량':item.get('restock_rec_qty'),'권장일':item.get('restock_rec_date')}
    sources=[]
    if row['wing']: sources.append('inventory')
    if row['api_stock'] is not None: sources.append('api_inventory')
    if row['price'] is not None: sources.append('api_prices')
    if row['recent_qty'] is not None: sources.append('api_orders')
    return {'id':'operations.option.'+row['option_id'],'label':f"{row['product_name']} · {row['option_name']}",'values':fields,'source_ids':sources}


def make_reply(snapshot, answer, facts, sources, gaps, followups, suggestions=None):
    used=[row for row in snapshot.get('sources',[]) if row['id'] in sources]
    return {'answer':'\n\n'.join(answer),'facts':facts,'sources':used,'uncertainties':gaps,'suggestions':suggestions or [],'followups':followups,
            'context_at':now().isoformat(),'snapshot_at':snapshot.get('generated_at'),
            'coverage':{'sources':len(used),'records':len(facts),'uncollected_scopes':len(gaps)},
            'model':'아르곤(Antigravity) 코칭 엔진 · 대시보드 직결','answer_origin':'아르곤 운영 브리핑 · 쿠팡 API & Wing 원본 대조'}


def _short_name(name, limit=20):
    s=str(name or '').strip()
    return s if len(s)<=limit+2 else s[:limit].rstrip()+'…'


def decline_report(snapshot, rows):
    window=snapshot.get('option_sales_windows')
    if not window:
        return ['비교에 필요한 완료된 주문 기간 2주가 아직 없습니다.'],[],['공식 API 주문 자료를 갱신하면 최근 7일과 직전 7일을 비교할 수 있습니다.']
    declines=[row for row in rows if row['recent_qty'] is not None and row['previous_qty'] is not None and row['recent_qty']<row['previous_qty']]
    declines.sort(key=lambda row:row['recent_qty']-row['previous_qty'])
    oos_cnt=sum(1 for r in declines if r['api_stock']==0)
    header=f"📌 주문 감소 요약 ({window['recent_start']}~{window['recent_end']} · 총 {len(declines)}건: 품절 영향 {oos_cnt}건 / 재고 보유 둔화 {len(declines)-oos_cnt}건)"
    bullets=[]
    for row in declines[:6]:
        stock=_stock_desc(row)
        option=row['option_name'] if row['option_name']!='옵션명 미확인' else '옵션 ID '+row['option_id']
        bullets.append(f"• {_short_name(row['product_name'])} / {option} : {row['previous_qty']:g} → {row['recent_qty']:g}개 ({stock})")
    if len(declines)>6:
        bullets.append(f"  …외 {len(declines)-6}건")
    lines=[header]
    if bullets: lines.append('\n'.join(bullets))
    if declines:
        lines.append("💡 코칭: 품절(재고 0개) 상품은 단품 입고를 앞당기고, 재고가 있는데 줄어든 상품은 아이템위너·가격을 점검하세요.")
    return lines,[option_fact(row) for row in declines],['출고 이후 조회 가능한 API 주문 기준입니다.']


def restock_report(rows, today):
    monday=today-timedelta(days=today.weekday())
    sunday=monday+timedelta(days=6)
    urgent=[]
    for row in rows:
        for item in row['wing']:
            due=iso_date(item.get('restock_rec_date'))
            qty=item.get('restock_rec_qty')
            if due is None or due>sunday or qty is None or qty<=0: continue
            inbound=item.get('stock_inbound')
            has_sales=any((value or 0)>0 for value in (row['recent_qty'],item.get('qty_7d'),item.get('qty_30d')))
            if inbound is None: category='입고 예정 확인'
            elif inbound>=qty: category='기존 입고 도착일 확인'
            elif inbound>0: category='기존 입고 도착일·추가 수량 검토'
            elif has_sales: category='추가 입고 우선 검토'
            else: category='판매 근거 확인 후 입고 검토'
            urgent.append((category,due,row,item))
    order={'추가 입고 우선 검토':0,'기존 입고 도착일·추가 수량 검토':1,'기존 입고 도착일 확인':2,'입고 예정 확인':3,'판매 근거 확인 후 입고 검토':4}
    urgent.sort(key=lambda entry:(order[entry[0]],entry[1],-(entry[2]['recent_qty'] or 0)))
    header=f"📌 이번 주 입고·발주 점검 ({monday.isoformat()}~{sunday.isoformat()} · 총 {len(urgent)}건)"
    bullets=[]
    facts=[]
    for i,(category,due,row,item) in enumerate(urgent):
        inbound=item.get('stock_inbound');qty=item['restock_rec_qty']
        if i<6:
            when=f"{due.isoformat()}"+(' 권장일 경과' if due<today else ' 권장일')
            planned='입고 예정 미확인' if inbound is None else f'입고 예정 {inbound:g}개'
            bullets.append(f"• {category} · {_short_name(row['product_name'])} / {row['option_name']} : {when}, 권장 {qty:g}개, {planned}")
        fact=option_fact(row)
        fact['id']=f"operations.restock.{row['option_id']}.{i}"
        fact['values'].update({'등급':item.get('grade'),'권장 입고일':due.isoformat(),'Wing 권장 입고수량(개)':qty,'입고 예정수량(개)':inbound,'확인할 일':category})
        facts.append(fact)
    if len(urgent)>6:
        bullets.append(f"  …외 {len(urgent)-6}건")
    lines=[header]
    if bullets: lines.append('\n'.join(bullets))
    if urgent:
        lines.append("💡 코칭: 입고 예정이 0개인 신규 보충 상품부터 먼저 발주하고, 예정 물량이 있는 상품은 도착일만 체크하세요.")
    return lines,facts,['Wing 권장일은 권장 시점입니다.']


def withdrawal_report(rows):
    candidates=[]
    for row in rows:
        for item in row['wing']:
            stock=item.get('stock_available')
            ages=[item.get(key) for key in ('age_61_120','age_121_180','age_181_plus')]
            if not stock or stock<0 or not any(value and value>0 for value in ages):
                continue
            aged=sum(value for value in ages if value is not None and value>0)
            if aged>stock:
                continue
            recent=row['recent_qty']
            prior=row['previous_qty']
            forecast=item.get('forecast_5w')
            wing_sales=item.get('qty_30d')
            quiet=recent==0 and prior==0 and not (wing_sales is not None and wing_sales>0)
            if quiet and (ages[2] or 0)>0:
                category='반출 우선 검토'
                priority=0
            elif quiet and forecast==0:
                category='재고 감축 검토'
                priority=1
            else:
                category='판매·예상수요 확인 후 검토'
                priority=2
            candidates.append((priority,category,row,item,ages,aged))
    candidates.sort(key=lambda entry:(entry[0],-(entry[4][2] or 0),-(entry[3].get('storage_fee_mtd') or 0),-entry[5]))
    priority_count=sum(item[0]==0 for item in candidates)
    reduce_count=sum(item[0]==1 for item in candidates)
    total_fee=sum((item[3].get('storage_fee_mtd') or 0) for item in candidates)
    lines=[f"📌 장기 재고 정리 요약 (반출 우선 검토 {priority_count}건 · 감축 검토 {reduce_count}건 · 전체 {len(candidates)}건 / 당월 보관비 {_fmt_won(total_fee)})"]
    if not candidates:
        lines.append('현재 61일 이상 장기 보관 재고가 없습니다.')
    bullets=[]
    facts=[]
    for i,(_,category,row,item,ages,aged) in enumerate(candidates):
        grade=item.get('grade') or '등급 미확인'
        fee=item.get('storage_fee_mtd')
        recent=row['recent_qty']
        prior=row['previous_qty']
        if i<6:
            older=f'181일 이상 {ages[2]:g}개' if ages[2] is not None else '181일+ 미확인'
            orders=f'7일 주문 {recent:g}개' if recent is not None else '주문 미확인'
            charge=f'보관비 {fee:,.0f}원' if fee is not None else '보관비 미확인'
            bullets.append(f"• {category} · {_short_name(row['product_name'])} / {row['option_name']} ({grade}) : 재고 {item['stock_available']:g}개({older}), {orders}, {charge}")
        fact=option_fact(row)
        fact['id']=f"operations.withdraw.{row['option_id']}.{i}"
        fact['values'].update({'등급':grade,'Wing 판매가능재고(개)':item['stock_available'],'61일 이상 보관 확인 수량(개)':aged,
            '61~120일 보관(개)':ages[0],'121~180일 보관(개)':ages[1],'181일 이상 보관(개)':ages[2],
            '당월 누적 보관비(원)':fee,'Wing 30일 판매수량(개)':item.get('qty_30d'),
            'Wing 예상 5주 판매수량(개)':item.get('forecast_5w'),'직전 7일 API 주문수량(옵션 단위)':prior,'검토 단계':category})
        facts.append(fact)
    if len(candidates)>6:
        bullets.append(f"  …외 {len(candidates)-6}건")
    if bullets: lines.append('\n'.join(bullets))
    if candidates:
        lines.append("💡 코칭: 181일 이상 무판매 재고는 할인 쿠폰으로 빠르게 처분하거나 반출 신청해 매달 나가는 보관비를 막으세요.")
    notes=['우선 검토는 181일 이상 재고가 있고 최근 2주 주문이 0인 항목입니다.']
    return lines,facts,notes


def _fmt_won(val):
    return '미확인' if val is None else f'{int(round(val)):,}원'


def _fmt_num(val, suffix='개'):
    return '미확인' if val is None else f'{val:,.0f}{suffix}'


def profit_report(snapshot, question):
    finance=snapshot.get('finance') or []
    if not finance:
        return None
    today=now().date()
    first_this=today.replace(day=1)
    last_prev=first_this-timedelta(days=1)
    first_prev=last_prev.replace(day=1)
    want_last=bool(re.search(r'지난\s*달|전월|저번\s*달',question))
    want_this=bool(re.search(r'이번\s*달|금월|당월',question))
    month_match=re.search(r'(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월',question)
    target_start=target_end=None
    label_period='최신 확보 기간'
    if month_match:
        yr=int(month_match[1]) if month_match[1] else today.year
        mo=int(month_match[2])
        if 1<=mo<=12:
            import calendar
            target_start=date(yr,mo,1).isoformat()
            target_end=date(yr,mo,calendar.monthrange(yr,mo)[1]).isoformat()
            label_period=f'{yr}년 {mo}월'
    elif want_last:
        target_start=first_prev.isoformat()
        target_end=last_prev.isoformat()
        label_period=f'지난 달({target_start}~{target_end})'
    elif want_this:
        target_start=first_this.isoformat()
        label_period=f'이번 달({target_start}~)'
    chosen=None
    if target_start and target_end:
        chosen=next((r for r in finance if r.get('start')==target_start and r.get('end')==target_end),None)
        if not chosen:
            chosen=next((r for r in finance if str(r.get('start','')).startswith(target_start[:7])),None)
    elif target_start:
        chosen=next((r for r in finance if r.get('start')==target_start),None)
    if not chosen:
        chosen=finance[0]
    p=snapshot.get('profit')
    use_profit=p and p.get('start')==chosen.get('start') and p.get('end')==chosen.get('end')
    rev=chosen.get('revenue'); exp=chosen.get('expenses'); comp=chosen.get('compensation'); wing_prof=chosen.get('profit')
    header=f"📌 손익 요약 ({chosen.get('start')}~{chosen.get('end')})"
    body=[
        f"• 총매출 {_fmt_won(rev)} / 재고보상 {_fmt_won(comp)}",
        f"• 윙 비용 {_fmt_won(exp)} (광고비 {_fmt_won(chosen.get('ads'))} · 물류비 {_fmt_won(chosen.get('fulfillment'))} · 수수료 {_fmt_won(chosen.get('commission'))})",
        f"• 원가 차감 전 윙 표시 이익: {_fmt_won(wing_prof)}"
    ]
    gaps=['Wing 표시 이익은 매출원가 차감 전 금액입니다.']
    if use_profit and p.get('confirmed'):
        body.append(f"• 입력 기준 순이익(매출원가 {_fmt_won(p.get('cogs'))} · 추가비용 {_fmt_won(p.get('extra'))} 반영): {_fmt_won(p.get('net_profit'))}")
        tip="💡 코칭: 입력하신 원가 기준 순이익이며, 최종 세금·환불 마감 전 수치입니다."
    else:
        tip="💡 코칭: 상단 ‘원가·추가 비용 입력’에서 해당 기간 매출원가를 입력하시면 최종 순이익이 즉시 계산됩니다."
    lines=[header,'\n'.join(body),tip]
    facts=[{'id':'finance.selected','label':f"윙 표시 수익 ({chosen.get('start')}~{chosen.get('end')})",'values':{k:chosen.get(k) for k in ('start','end','revenue','expenses','profit','ads','fulfillment','commission','compensation','captured_at') if k in chosen},'source_ids':['finance']}]
    if use_profit:
        facts.append({'id':'profit.overview','label':'동일 기간 손익 · 입력 기준','values':{'시작일':p.get('start'),'종료일':p.get('end'),'총매출(원)':p.get('revenue'),'확보된 윙 비용(원)':p.get('wing_cost'),'입력한 매출원가(원)':p.get('cogs'),'입력한 추가 비용(원)':p.get('extra'),'입력 기준 순이익·미확정(원)':p.get('net_profit'),'상태':p.get('status')},'source_ids':['finance']})
    return lines,facts,{'finance'},gaps


def ads_report(snapshot, question):
    ads=snapshot.get('ads')
    billing=snapshot.get('billing')
    ad_products=snapshot.get('ad_products') or []
    ad_period=snapshot.get('ad_period')
    campaigns=snapshot.get('campaigns') or []
    finance=snapshot.get('finance') or []
    if not (ads or billing or ad_products or campaigns):
        return None
    summary_lines=['📌 광고 성과 요약']; facts=[]; sources=set()
    if finance:
        today=now().date()
        first_this=today.replace(day=1)
        last_prev=first_this-timedelta(days=1)
        first_prev=last_prev.replace(day=1)
        want_last=bool(re.search(r'지난\s*달|전월|저번\s*달',question))
        f_row=next((r for r in finance if r.get('start')==first_prev.isoformat() and r.get('end')==last_prev.isoformat()),None) if want_last else finance[0]
        if not f_row: f_row=finance[0]
        if f_row and f_row.get('ads') is not None:
            ad_val=abs(int(f_row['ads']))
            rev_val=int(f_row.get('revenue') or 0)
            ratio_txt=f" (매출 대비 {ad_val/rev_val*100:.1f}%)" if rev_val>0 else ""
            summary_lines.append(f"• 수익현황 광고비({f_row.get('start')}~{f_row.get('end')}): {_fmt_won(f_row.get('ads'))}{ratio_txt}")
            facts.append({'id':'finance.ads_period','label':f"윙 표시 수익 · 광고비 ({f_row.get('start')}~{f_row.get('end')})",'values':{k:f_row.get(k) for k in ('start','end','revenue','ads','expenses','profit') if k in f_row},'source_ids':['finance']})
            sources.add('finance')
    if ads:
        req_margin=round(ads['spend']/ads['sales']*100,1) if ads.get('spend') and ads.get('sales') else None
        m_txt=f" (손익분기 마진율 {req_margin}%)" if req_margin else ""
        summary_lines.append(f"• 광고센터({ads.get('start')}~{ads.get('end')}): 집행 {_fmt_won(ads.get('spend'))} → 전환매출 {_fmt_won(ads.get('sales'))} (ROAS {ads.get('roas','미확인')}%{m_txt})")
        facts.append({'id':'ads','label':'광고센터 요약','values':ads,'source_ids':['ads']})
        sources.add('ads')
    if billing:
        summary_lines.append(f"• {billing.get('month')}월 청구액: {_fmt_won(billing.get('bill'))} (과금 {_fmt_won(billing.get('eligible'))} + VAT {_fmt_won(billing.get('vat'))})")
        facts.append({'id':'billing','label':'광고비 청구','values':billing,'source_ids':['ads']})
        sources.add('ads')
    lines=['\n'.join(summary_lines)]
    if ad_products:
        zero_conv=[r for r in ad_products if (r.get('spend') or 0)>0 and (r.get('sales_14d') or 0)==0]
        low_roas=[r for r in ad_products if (r.get('spend') or 0)>0 and 0<(r.get('roas') or 0)<200]
        top_spend=ad_products[:4]
        prod_lines=[f"🔍 점검 대상 광고 옵션 (무전환 지출 {len(zero_conv)}개 · ROAS 200% 미만 {len(low_roas)}개)"]
        for r in (zero_conv[:3]+low_roas[:2]+top_spend[:2])[:5]:
            roas_txt='0% (무전환)' if (r.get('sales_14d') or 0)==0 else f"{r.get('roas',0):.1f}%"
            prod_lines.append(f"• {_short_name(r.get('product'))} : 광고비 {_fmt_won(r.get('spend'))} → 전환 {_fmt_won(r.get('sales_14d'))} (ROAS {roas_txt})")
        lines.append('\n'.join(prod_lines))
        for i,r in enumerate(ad_products[:10]):
            facts.append({'id':f'ad_products.{i}','label':'광고 상품 성과','values':{'상품':r.get('product'),'옵션 ID':r.get('option_id'),'광고비(원)':r.get('spend'),'광고 전환매출·14일 기여(원)':r.get('sales_14d'),'클릭수':r.get('clicks'),'전환 주문수·14일 기여':r.get('orders_14d'),'ROAS(%)':round(r['roas'],2) if r.get('roas') is not None else None},'source_ids':['ad_detail']})
        sources.add('ad_detail')
    lines.append("💡 코칭: 전환매출이 0원인 무전환 옵션부터 캠페인에서 제외하거나 입찰가를 낮춰 광고비 누수를 막으세요.")
    gaps=['광고센터 집행액과 청구액은 집계 기준이 다릅니다.']
    return lines,facts,sources,gaps


def returns_report(snapshot, rows, matches):
    returns=snapshot.get('returns') or []
    comp=snapshot.get('compensation') or []
    insight=snapshot.get('return_insight')
    lines=[]; facts=[]; sources=set()
    target_ids={r['option_id'] for r in matches} if matches else None
    scoped=[r for r in returns if not target_ids or str(r.get('option_id')) in target_ids]
    if not returns:
        return None
    sources.add('returns')
    overdue=[r for r in scoped if r.get('overdue')]
    status_counts=Counter(r.get('process_status','미확인') for r in scoped)
    status_txt=', '.join(f'{k} {v}건' for k,v in status_counts.most_common())
    head=[f"📌 반품 현황 요약 (총 {len(scoped)}건: {status_txt} · 90일+ 장기 회수중 {len(overdue)}건)"]
    if insight and not matches:
        head.append(f"• {insight.get('month')}월 윙 표시 반품률: {insight.get('rate')}% (분석 상품 {insight.get('products')}건)")
        facts.append({'id':'return_insight','label':'윙 표시 반품률','values':insight,'source_ids':['return_insight']})
        sources.add('return_insight')
    if comp:
        comp_scoped=[c for c in comp if not target_ids or str(c.get('option_id')) in target_ids]
        total_comp=sum(c.get('compensation_amount',0) for c in comp_scoped)
        head.append(f"• 재고 손실 보상 완료: {len(comp_scoped)}건 (합계 {_fmt_won(total_comp)})")
        sources.add('compensation')
        for i,c in enumerate(comp_scoped[:6]):
            facts.append({'id':f'compensation.{i}','label':'재고 손실 보상','values':{k:c.get(k) for k in ('event_date','period_end','product_name','option_name','event_type','damage_type','compensation_amount') if k in c},'source_ids':['compensation']})
    lines.append('\n'.join(head))
    by_prod=Counter((r.get('product_name',''),str(r.get('option_id',''))) for r in scoped)
    prod_lines=[]
    for (pname,oid),cnt in by_prod.most_common(5):
        ov=sum(1 for r in scoped if str(r.get('option_id'))==oid and r.get('overdue'))
        top_reason=Counter(r.get('reason','미확인') for r in scoped if str(r.get('option_id'))==oid).most_common(1)
        r_txt=top_reason[0][0] if top_reason else '미확인'
        prod_lines.append(f"• {_short_name(pname)} : 반품 {cnt}건" + (f" (90일+ 회수중 {ov}건)" if ov else "") + f" · 사유: {r_txt}")
    if prod_lines: lines.append('\n'.join(prod_lines))
    facts.insert(0,{'id':'returns.summary','label':'반품 접수 요약','values':{'접수 건수':len(scoped),'90일 이상 회수중 접수 건수':len(overdue),'상태별 건수':dict(status_counts)},'source_ids':['returns']})
    grouped=Counter((r.get('product_name',''),str(r.get('option_id','')),r.get('process_status',''),r.get('reason','')) for r in scoped)
    for i,((product,option,status,reason),count) in enumerate(grouped.most_common(10)):
        facts.append({'id':f'returns.group.{i}','label':'상품별 반품 접수','values':{'상품':product,'옵션 ID':option,'처리 상태':status,'반품 사유':reason,'접수 건수':count},'source_ids':['returns']})
    lines.append("💡 코칭: 90일 이상 경과한 장기 '회수중' 건은 쿠팡윙에서 회수 완료 및 손실 보상 정산 여부를 확인하세요.")
    gaps=['반품 엑셀은 접수 건수 기준입니다.']
    return lines,facts,sources,gaps


def catalog_report(snapshot, rows):
    summary=snapshot.get('summary') or {}
    active_rows=[r for r in rows if r.get('active_listing') or (r.get('api_stock') or 0)>0 or (r.get('recent_qty') or 0)>0]
    families=len({r.get('product_id') or normalized(r['product_name']) for r in active_rows if r['product_name']!='등록상품명 미확인'})
    header=(f"📌 스토어 현황 요약 (전체 옵션은 {len(rows)}개 · 상품군 {families}종)\n"
            f"• API 재고 합계 {_fmt_num(summary.get('api_stock'))} / 30일 판매금액 {_fmt_won(summary.get('revenue30'))}\n"
            f"• 품절 {summary.get('out_of_stock',0)}건 / 입고 검토 {summary.get('restock',0)}건 / 원가 미입력 {summary.get('missing_costs',0)}건")
    ranked=sorted(active_rows,key=lambda r:((r.get('recent_qty') or 0),sum((w.get('rev_30d') or 0) for w in r['wing']),(r.get('api_stock') or 0)),reverse=True)
    bullets=['📦 주요 옵션 현황 (상위 6개)']
    for r in ranked[:6]:
        stock=_stock_desc(r,short=True)
        sold=_fmt_num(r['recent_qty'])
        price=_fmt_won(r['price'])
        bullets.append(f"• {_short_name(r['product_name'])} / {r['option_name']} : 7일 주문 {sold}, 재고 {stock}, 판매가 {price}")
    lines=[header,'\n'.join(bullets)]
    facts=[{'id':'inventory.summary','label':'재고 운영 요약','values':{'API 판매가능재고 합계(개)':summary.get('api_stock'),'Wing 엑셀 판매가능재고 합계(개)':summary.get('inventory_stock'),'Wing 30일 판매금액(원)':summary.get('revenue30'),'품절 항목':summary.get('out_of_stock'),'입고 검토 항목':summary.get('restock'),'매입원가 미입력 항목':summary.get('missing_costs')},'source_ids':['inventory','api_inventory']}]
    facts.extend(option_fact(r) for r in ranked[:15])
    gaps=['공식 API 재고는 옵션 ID 단위입니다.']
    return lines,facts,{'inventory','api_inventory','api_prices','api_orders'},gaps


def diagnosis_report(snapshot, rows):
    summary=snapshot.get('summary') or {}
    today=now().date()
    _,restock_facts,_=restock_report(rows,today)
    _,decline_facts,_=decline_report(snapshot,rows)
    _,withdraw_facts,_=withdrawal_report(rows)
    selling_oos=[r for r in rows if r.get('api_stock')==0 and not r.get('bundle_base_option') and ((r.get('recent_qty') or 0)>0 or (r.get('previous_qty') or 0)>0 or any((w.get('qty_30d') or 0)>0 for w in r['wing']))]
    ads=snapshot.get('ads') or {}
    ad_products=snapshot.get('ad_products') or []
    zero_ad=[r for r in ad_products if (r.get('spend') or 0)>0 and (r.get('sales_14d') or 0)==0]
    oos_names=', '.join(f"{_short_name(r['product_name'],10)}({r['option_name']})" for r in selling_oos[:3])
    oos_sfx=f" ({oos_names} 등)" if oos_names else ""
    body=[
        f"1) [재고·입고 보완] 판매 중 품절 단품 {len(selling_oos)}개{oos_sfx} · 이번 주 입고 검토 {len(restock_facts)}건",
        f"2) [판매 흐름 점검] 최근 7일 주문 감소 {len(decline_facts)}개 옵션 (품절 영향 vs 노출·가격 점검)",
        f"3) [장기 재고·보관비 절감] 장기 보관 검토 {len(withdraw_facts)}건 (181일+ 무판매 재고 반출·할인 처분)",
        f"4) [수익성·광고·원가] 광고 ROAS {ads.get('roas','미확인')}% (무전환 지출 {len(zero_ad)}개) · 원가 미입력 {summary.get('missing_costs',0)}건",
        f"5) [반품·회수 관리] 90일+ 장기 미회수 반품 {summary.get('overdue_returns',0)}건 (전체 {summary.get('return_cases',0)}건)"
    ]
    lines=[
        "📌 왓니몰 오늘의 핵심 점검 요약",
        '\n'.join(body),
        "💡 추천 실행 순서: ① 품절 효자상품 입고 → ② 181일+ 장기재고 반출/할인 → ③ 무전환 광고 OFF 및 원가 입력"
    ]
    facts=[{'id':'inventory.summary','label':'운영 핵심 요약','values':{'품절 항목':summary.get('out_of_stock'),'판매 중 품절 옵션 수':len(selling_oos),'이번 주 입고 검토(건)':len(restock_facts),'최근 7일 주문 감소 옵션 수':len(decline_facts),'장기 보관 검토(건)':len(withdraw_facts),'매입원가 미입력 항목':summary.get('missing_costs'),'90일 이상 회수중 반품(건)':summary.get('overdue_returns')},'source_ids':['inventory','api_inventory','api_orders','returns']}]
    if snapshot.get('finance'):
        f0=snapshot['finance'][0]
        facts.append({'id':'finance.0','label':f"윙 표시 수익 ({f0.get('start')}~{f0.get('end')})",'values':{k:f0.get(k) for k in ('start','end','revenue','expenses','profit','ads','fulfillment','commission','compensation') if k in f0},'source_ids':['finance']})
    if ads:
        facts.append({'id':'ads','label':'광고센터 요약','values':ads,'source_ids':['ads']})
    facts.extend((restock_facts[:3]+decline_facts[:3]+withdraw_facts[:3])[:8])
    sources={'inventory','api_inventory','api_orders','returns','finance','ads'}
    gaps=['매입원가 미입력 항목이 남아 있어 전체 순이익은 원가 입력 후 확정됩니다.']
    return lines,facts,sources,gaps


def oos_report(snapshot, rows):
    selling_oos=[]
    other_oos=[]
    low_stock=[]
    for row in rows:
        api_st=row.get('api_stock')
        wing_st=sum((w.get('stock_available') or 0) for w in row['wing']) if row['wing'] else None
        is_zero=(api_st==0) or (api_st is None and wing_st==0 and bool(row['wing']))
        has_sales=any((v or 0)>0 for v in (row.get('recent_qty'),row.get('previous_qty'),*[w.get('qty_30d') for w in row['wing']]))
        if is_zero:
            if has_sales: selling_oos.append(row)
            elif row.get('active_listing'): other_oos.append(row)
        elif api_st is not None and 0<api_st<=5 and has_sales:
            low_stock.append(row)
    selling_oos.sort(key=lambda r:(bool(r.get('bundle_base_option')),-(r.get('recent_qty') or 0),-(r.get('previous_qty') or 0),-sum((w.get('qty_30d') or 0) for w in r['wing'])))
    low_stock.sort(key=lambda r:(bool(r.get('bundle_base_option')),r.get('api_stock') or 99,-(r.get('recent_qty') or 0)))
    header=f"📌 품절·품절임박 요약 (판매 중 품절 {len(selling_oos)}건 · 품절임박 {len(low_stock)}건)"
    bullets=[]; facts=[]
    for r in selling_oos[:5]:
        inbound=sum((w.get('stock_inbound') or 0) for w in r['wing']) if r['wing'] else (r.get('bundle_base_inbound') or 0)
        if r.get('bundle_base_option'):
            in_txt=f"모체({r['bundle_base_option']}) 입고예정 {inbound:g}개" if inbound>0 else f"모체({r['bundle_base_option']}) 발주 시급"
        else:
            in_txt=f"입고예정 {inbound:g}개" if inbound>0 else "입고예정 없음(발주 시급)"
        bullets.append(f"• [품절·판매중] {_short_name(r['product_name'])} / {r['option_name']} : 7일 주문 {_fmt_num(r['recent_qty'])} · {in_txt}")
        facts.append(option_fact(r))
    for r in low_stock[:3]:
        inbound=sum((w.get('stock_inbound') or 0) for w in r['wing']) if r['wing'] else (r.get('bundle_base_inbound') or 0)
        bullets.append(f"• [품절임박] {_short_name(r['product_name'])} / {r['option_name']} : 재고 {_stock_desc(r,short=True)}, 7일 주문 {_fmt_num(r['recent_qty'])}, 입고예정 {inbound:g}개")
        facts.append(option_fact(r))
    lines=[header]
    if bullets: lines.append('\n'.join(bullets))
    lines.append("💡 코칭: 입고 예정이 없는 품절 상품부터 즉시 발주해 노출 순위 하락을 막으세요.")
    gaps=['API 판매가능재고는 최신 수집 시각 기준입니다.']
    return lines,facts,{'inventory','api_inventory','api_orders'},gaps


def bestseller_report(snapshot, rows):
    ranked=sorted(
        [r for r in rows if (r.get('recent_qty') or 0)>0 or (r.get('previous_qty') or 0)>0 or any((w.get('rev_30d') or 0)>0 for w in r['wing'])],
        key=lambda r:((r.get('recent_qty') or 0),sum((w.get('rev_30d') or 0) for w in r['wing']),sum((w.get('qty_30d') or 0) for w in r['wing'])),
        reverse=True
    )
    window=snapshot.get('option_sales_windows')
    w_txt=f"({window['recent_start']}~{window['recent_end']} 7일 주문 & 30일 매출 기준)" if window else "(30일 매출 기준)"
    header=f"📌 베스트셀러 효자 옵션 TOP 6 {w_txt}"
    bullets=[]; facts=[]
    for idx,r in enumerate(ranked[:6],1):
        w_rev=sum((w.get('rev_30d') or 0) for w in r['wing'])
        stock=_stock_desc(r,short=True)
        warn=" ⚠️품절" if r.get('api_stock')==0 else (" ⚠️재고부족" if r.get('api_stock') is not None and r.get('api_stock')<=5 else "")
        bullets.append(f"{idx}위 · {_short_name(r['product_name'])} / {r['option_name']} : 7일 주문 {_fmt_num(r['recent_qty'])}, 30일 매출 {_fmt_won(w_rev)}, 재고 {stock}{warn}")
        facts.append(option_fact(r))
    lines=[header,'\n'.join(bullets),"💡 코칭: 상위 효자 옵션 중 품절·재고부족 표시가 뜬 상품은 최우선으로 안전재고를 채워주세요."]
    gaps=['최근 7일 주문수량은 공식 API 기준입니다.']
    return lines,facts,{'inventory','api_inventory','api_orders','api_prices'},gaps


def sales_trend_report(snapshot):
    daily=snapshot.get('daily') or []
    comp=snapshot.get('revenue_comparison') or {}
    summary=snapshot.get('summary') or {}
    if not daily and not comp:
        return None
    header=f"📌 최근 30일 매출 요약: API 주문금액 {_fmt_won(comp.get('api_amount'))} ({_fmt_num(comp.get('api_order_count'),'건')}) / 윙 보고서 {_fmt_won(summary.get('revenue30'))}"
    lines=[header]
    if daily:
        recent_7=daily[-7:]
        rev_7=sum(d.get('revenue',0) for d in recent_7)
        ord_7=sum(d.get('orders',0) for d in recent_7)
        avg_7=round(rev_7/len(recent_7)) if recent_7 else 0
        bullets=[f"📊 최근 7일 합계 {_fmt_won(rev_7)} ({ord_7}건 · 일평균 {_fmt_won(avg_7)})"]
        for d in reversed(recent_7):
            bullets.append(f"• {d.get('date')} : {_fmt_won(d.get('revenue'))} ({d.get('orders',0)}건 · {d.get('quantity',0)}개)")
        lines.append('\n'.join(bullets))
    facts=[
        {'id':'sales.api','label':'API 주문상품 금액','values':{'금액(원)':comp.get('api_amount'),'시작일':comp.get('api_start'),'종료일':comp.get('api_end'),'주문 건수':comp.get('api_order_count'),'판매수량(개)':comp.get('api_quantity')},'source_ids':['api_orders']},
        {'id':'sales.excel','label':'재고 보고서 판매금액','values':{'금액(원)':summary.get('revenue30'),'판매수량(개)':summary.get('sold30')},'source_ids':['inventory']},
    ]
    for i,d in enumerate(reversed(daily[-5:])):
        facts.append({'id':f'daily.recent.{i}','label':f"일별 주문 ({d.get('date')})",'values':d,'source_ids':['api_orders']})
    gaps=['API 주문상품 금액은 출고일 이후 지원 주문 기준입니다.']
    return lines,facts,{'api_orders','inventory'},gaps


def cost_master_report(snapshot):
    analysis=snapshot.get('cost_analysis') or {}
    inv=snapshot.get('inventory') or []
    if not analysis and not inv:
        return None
    total=analysis.get('total') or len(inv)
    entered=analysis.get('entered') or sum(1 for r in inv if r.get('unit_cost') is not None)
    missing=total-entered
    head=[f"📌 매입원가 마스터 입력 현황 (전체 {total}개 중 {entered}개 완료 · {missing}개 미입력)"]
    if analysis.get('matched'):
        head.append(f"• 입력 항목({analysis.get('matched')}개) 기준: 판매금액 {_fmt_won(analysis.get('revenue'))}, 원가 차감액 {_fmt_won(analysis.get('gross'))} (차감률 {analysis.get('margin','미확인')}%)")
    lines=['\n'.join(head)]
    missing_selling=[r for r in inv if r.get('unit_cost') is None and ((r.get('rev_30d') or 0)>0 or (r.get('qty_30d') or 0)>0 or (r.get('stock_available') or 0)>0)]
    missing_selling.sort(key=lambda r:(-(r.get('rev_30d') or 0),-(r.get('stock_available') or 0)))
    if missing_selling:
        bullets=[f"📝 원가 우선 입력 대상 (상위 5개)"]
        for r in missing_selling[:5]:
            bullets.append(f"• {_short_name(r.get('product_name'))} / {r.get('option_name')} : 30일 매출 {_fmt_won(r.get('rev_30d'))}, 재고 {_fmt_num(r.get('stock_available'))}")
        lines.append('\n'.join(bullets))
    facts=[{'id':'cost.analysis','label':'입력 원가 기반 지표','values':{'전체 항목 수':total,'원가 입력 항목 수':entered,'미입력 항목 수':missing,'판매분 원가 차감 금액(원)':analysis.get('gross'),'원가 차감률(%)':analysis.get('margin')},'source_ids':['inventory']}]
    gaps=['좌측 매입원가 · 수익성 메뉴에서 단위원가를 입력할 수 있습니다.']
    return lines,facts,{'inventory'},gaps


def operations_reply(snapshot,question,history=None,*,intents=None,option_ids=(),product_scope=False):
    restock=bool(re.search(r'이번\s*주.*(?:입고|발주|보충|채워|채울|넣어|넣을)|(?:입고|발주|보충|물량\s*채워|물량\s*보충).*이번\s*주|추가\s*입고(?:할|해야|\s*추천|\s*상품|\s*후보)|(?:입고|발주|재입고)\s*(?:할|해야|필요|대상|후보|검토|추천|상품|제품|옵션|항목|종목|품목|뭐|뭘까|알려)|권장\s*입고|(?:재고|물량|수량).{0,20}(?:늘려|늘릴|늘려야|보충|채워|채울|더\s*넣)|더\s*넣어야',question))
    sales=bool(re.search(r'판매\s*(?:량|수량|속도|실적|추이|흐름)|주문\s*(?:량|수량)|판매가?\s*(?:안\s*되|안되|부진|저조|줄|하락|감소)|덜\s*팔|안\s*팔|안팔리|잘\s*안\s*(?:팔|나가)|안\s*나가는',question))
    decline=sales and bool(re.search(r'부족|감소|떨어|하락|줄|덜\s*팔|안\s*팔|안팔리|안\s*되|안되|안\s*나가|둔화|저조|부진|빠진|줄어',question))
    withdraw=bool(re.search(r'반출|(?:재고|물량|제품|상품).{0,30}(?:빼야|빼면|뺄|빼는|줄일|줄여|줄여야|감축|정리|처분|치워|치울)|(?:장기\s*(?:보관|재고)|과잉\s*재고|악성\s*재고|체화\s*재고|묶인\s*재고)|자리만\s*차지|창고.{0,20}(?:자리|차지|빼|정리|오래)|보관비|창고비|보관료',question))
    diagnosis=bool(re.search(r'부족하(?:거나|고)|보완해야|개선해야|문제(?:점|가\s*뭐|있는)|앞으로|미래에|먼저\s*(?:확인|해야)|우선순위|전체\s*(?:상황|브리핑|점검)|종합\s*(?:진단|점검|분석)|사업.*어떻게|코치|점검할\s*것|오늘\s*(?:할\s*일|뭐\s*해야)|내가\s*뭘\s*해야|해야\s*(?:될|할)\s*일|(?:지금|현재|당장).{0,15}(?:해야|할\s*일|체크할|챙겨야)|어떻게\s*운영',question))
    catalog_all=bool(re.search(r'(?:전체|모든|우리|왓니몰)\s*(?:상품|제품|옵션|재고).*(?:알려|보여|뭐|현황|목록|리스트)|상품(?:들|이랑|과)?\s*재고\s*(?:현황|전체|목록|알려)|무슨\s*상품\s*팔|파는\s*상품\s*(?:목록|현황|전체|알려)',question))
    diff_question=bool(re.search(r'(?:판매\s*금액|매출).*(?:주문\s*상품\s*금액|API\s*금액).*(?:다르|차이|달라|차액)|(?:판매\s*금액|매출)\s*차이',question))
    ask_oos=bool(re.search(r'품절|재고\s*(?:0개|없는|부족한|바닥|떨어진)|다\s*팔린\s*(?:상품|제품|옵션)',question)) and not restock
    ask_bestseller=bool(re.search(r'잘\s*팔리|많이\s*팔리|제일\s*잘\s*나가|잘\s*나가는|베스트\s*셀러|효자|최고\s*매출|매출\s*(?:최고|1위|1등|상위|순위|높은|많은)|판매량?\s*(?:최고|1위|1등|상위|순위|높은|많은)|인기\s*(?:상품|제품|종목|품목|옵션)',question))
    ask_sales=bool(re.search(r'(?:최근|일별|오늘|어제|이번\s*주|30일)\s*(?:매출|주문\s*현황|판매\s*금액|실적)|(?:매출|주문)\s*(?:추이|흐름|현황)\s*(?:알려|보여|어때)|매출이?\s*얼마',question)) and bool(snapshot.get('daily')) and not diff_question and not ask_bestseller
    ask_cost=bool(re.search(r'(?:원가|단위원가|매입원가).*(?:미입력|안\s*넣|입력\s*안|없는|현황|분석|목록)|(?:미입력|입력\s*안\s*된|안\s*넣은).*(?:원가|단위원가|매입원가)|마진율?\s*(?:분석|현황|좋은|높은|낮은|어때)',question)) and bool(snapshot.get('cost_analysis') or snapshot.get('inventory')) and not bool(re.search(r'위안|CNY|관세|수입할|수입비|수입\s*원가',question,re.I))
    ask_returns=bool(re.search(r'반품|회수\s*중|장기\s*미회수|보상\s*내역',question)) and not diff_question
    ask_ads=bool(re.search(r'광고|ROAS|로아스|캠페인|전환\s*매출',question)) and not bool(re.search(r'수입\s*원가|위안|CNY',question,re.I)) and not diff_question
    ask_profit=bool(re.search(r'(?:지난\s*달|이번\s*달|전월|금월|당월|\d+\s*월|현재|지금|전체|윙)\s*(?:순이익|손익|이익|수익|적자|흑자|정산)|^(?:순이익|손익|이익|수익)(?:은|이|\s*얼마|\s*어때|\?)|순이익\s*(?:얼마|어때|\?)|돈\s*얼마나\s*벌',question)) and not bool(re.search(r'\d+\s*개\s*(?:를\s*)?(?:다\s*|전부\s*|모두\s*)?(?:판매|팔)|완판|위안|CNY|수입',question,re.I)) and not diff_question
    ask_greeting=bool(re.search(r'^(?:안녕|반가워|하이|헬로)|이름이?\s*뭐|누구(?:야|니|세요|십니까)|정체가?\s*뭐|너는?\s*누구|자기\s*소개|무슨\s*모델|아르곤\s*맞',question.strip()))
    ask_refresh=bool(re.search(r'(?:전체\s*자료|전체\s*갱신|새로\s*고침).*(?:api|차이|다르|정확|얼마나|자주)|(?:api\s*갱신|빠른\s*갱신).*(?:전체|차이|다르|정확|얼마나|자주)|무엇을\s*갱신하고|얼마나\s*자주\s*누를',question,re.I))
    if intents is not None:
        restock=bool('restock' in intents)
        decline=bool('decline' in intents)
        withdraw=bool('withdraw' in intents)
        ask_ads=bool('ads' in intents)
        ask_returns=bool('returns' in intents)
        ask_profit=bool('profit' in intents)
        diagnosis=bool('diagnosis' in intents)
        catalog_all=bool('catalog' in intents)
        ask_oos=bool('oos' in intents)
        ask_bestseller=bool('bestseller' in intents)
        ask_sales=bool('sales' in intents)
        ask_cost=bool('cost' in intents)
        ask_greeting=False
        ask_refresh=False
        if not any((restock,decline,withdraw,ask_ads,ask_returns,ask_profit,diagnosis,catalog_all,ask_oos,ask_bestseller,ask_sales,ask_cost)): return None
    if re.search(r'다음\s*주|지난\s*주\s*입고|입고\s*(?:신청해|등록해|발주해)',question): return None
    if sales and not (ask_profit or ask_ads or diagnosis or withdraw or ask_sales or ask_bestseller) and re.search(r'오늘|어제|지난\s*달|이번\s*달|\d+\s*일\s*동안|\d+\s*월',question): return None
    rows=list(operations_rows(snapshot))
    matches=product_matches(rows,question) if rows else []
    if requested_ids(question) and not matches:
        return make_reply(snapshot,['입력한 상품·옵션 ID와 일치하는 운영 자료를 찾지 못했습니다.'],[],set(),['쿠팡에 표시된 옵션 ID나 등록상품명을 확인해 주세요.'],[])
    if not matches and option_ids:
        matches=[row for row in rows if row['option_id'] in option_ids]
        if not matches and product_scope: return None
    if not matches and re.search(r'그\s*(?:상품|옵션|제품)|이\s*(?:상품|옵션|제품)|해당\s*(?:상품|옵션)',question):
        latest=next((turn for turn in reversed(history or []) if turn.get('state','complete')=='complete'),{})
        ids=(latest.get('reply') or {}).get('operations_option_ids',[])
        matches=[row for row in rows if row['option_id'] in ids]
        if not matches and (restock or decline or withdraw): return None
    if product_scope and not matches:
        return None
    if not rows and not (ask_profit or ask_ads or ask_returns or ask_sales or ask_cost or ask_refresh):
        return None
    facts=[]; gaps=[]; answer=[]; source_ids=set(); suggestions=[]
    if ask_refresh and not diagnosis:
        answer=[
            "📌 갱신 방식 차이 및 정확도 한눈 요약\n"
            "• ⚡ API만 빠르게 갱신 (약 2~10초 · 수시 권장) : 크롬 로그인 없이 쿠팡 서버 직결 · 실시간 판매가능재고(묶음연동 포함)·최근 30일 주문·등록 판매가·API 반품 4종 수집 · 정확도 100%(실시간 원장 기준)\n"
            "• 📦 전체 자료 새로고침 (약 20~45초 · 하루 1~2회) : API 4종 + 쿠팡윙 전용 5종(창고 입고예정·보관일수·손익/수수료·정산 예정금·광고 ROAS·90일+ 장기반품) 통합 수집 · 정확도 100%(쿠팡윙 원본 일치)",
            "💡 코칭: 평소 주문·재고 확인은 ‘⚡ API만 빠르게 갱신’을 수시로 누르시고, 아침 출근 직후나 광고·정산·창고 보관일 점검 때만 ‘📦 전체 자료 새로고침’을 눌러주세요."
        ]
        source_ids.update(('api_inventory','api_orders','inventory','finance'))
    if diagnosis:
        report,items,srcs,notes=diagnosis_report(snapshot,matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
        suggestions.extend(['판매 중 품절된 핵심 옵션의 물류센터 입고 예정일 확인 및 추가 발주하기','181일 이상 무판매 장기재고 반출 신청 또는 할인 쿠폰 적용하기','좌측 매입원가 메뉴에서 매출 상위 상품의 단위원가 입력하기'])
    if catalog_all and not diagnosis:
        report,items,srcs,notes=catalog_report(snapshot,matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
    if restock and not diagnosis:
        report,items,notes=restock_report(matches or rows,now().date())
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.add('inventory')
        suggestions.extend(['입고 예정이 0개인 추가 입고 우선 검토 상품부터 발주 수량 확정하기','기존 입고 예정 수량이 있는 상품은 쿠팡윙에서 실제 입고 완료 여부 확인하기'])
    if withdraw and not diagnosis:
        report,items,notes=withdrawal_report(matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(('inventory','api_orders'))
        suggestions.extend(['181일 이상 보관 + 최근 주문 0개 상품의 반출 배송비와 할인 처분 회수액 비교하기','쿠팡윙 재고현황에서 장기보관 품목 반출 신청 또는 재고 소진 프로모션 설정하기'])
    if decline and not diagnosis:
        report,items,notes=decline_report(snapshot,matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.add('api_orders')
        suggestions.extend(['API 재고 0개로 주문이 줄어든 옵션은 입고 일정 앞당기기','재고가 충분한데 주문이 감소한 옵션은 아이템위너·판매가·광고 노출 점검하기'])
    if ask_oos and not diagnosis:
        report,items,srcs,notes=oos_report(snapshot,matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
        suggestions.extend(['입고 예정이 없는 판매 중 품절 옵션 우선 발주하기','품절 임박(재고 5개 이하) 옵션 안전재고 보충하기'])
    if ask_bestseller and not diagnosis:
        report,items,srcs,notes=bestseller_report(snapshot,matches or rows)
        answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
    if ask_sales and not diagnosis:
        if res:=sales_trend_report(snapshot):
            report,items,srcs,notes=res
            answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
    if ask_cost and not diagnosis:
        if res:=cost_master_report(snapshot):
            report,items,srcs,notes=res
            answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
            suggestions.extend(['좌측 매입원가 · 수익성 메뉴에서 매출 상위 미입력 상품부터 단위원가 저장하기'])
    if ask_profit and not diagnosis:
        if res:=profit_report(snapshot,question):
            report,items,srcs,notes=res
            answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
            suggestions.extend(['대시보드 상단 원가·추가 비용 입력 창에서 해당 기간 판매분 매출원가 반영하기'])
    if ask_ads and not diagnosis:
        if res:=ads_report(snapshot,question):
            report,items,srcs,notes=res
            answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
            suggestions.extend(['전환매출이 0원인 광고 지출 옵션의 키워드·입찰가 점검 또는 캠페인 제외 검토하기','상품별 매입원가를 입력해 손익분기 ROAS 기준선 확정하기'])
    if ask_returns and not diagnosis:
        if res:=returns_report(snapshot,rows,matches):
            report,items,srcs,notes=res
            answer.extend(report);facts.extend(items);gaps.extend(notes);source_ids.update(srcs)
            suggestions.extend(['90일 이상 경과한 회수중 반품 건의 쿠팡윙 회수 완료 및 보상 정산 여부 확인하기'])
    if ask_greeting and not answer:
        summary=snapshot.get('summary') or {}
        comp=snapshot.get('revenue_comparison') or {}
        answer=[
            "👋 안녕하세요 사장님! 왓니몰 전담 ‘아르곤(Antigravity)’ 에이전트입니다.\n"
            f"• 실시간 연동: 전체 {len(rows)}개 옵션 · 판매가능재고 {_fmt_num(summary.get('api_stock'))} · 30일 주문금액 {_fmt_won(comp.get('api_amount'))}\n"
            f"• 오늘 체크포인트: 입고 검토 {summary.get('restock',0)}건 · 품절 {summary.get('out_of_stock',0)}건 · 반품 {summary.get('return_cases',0)}건",
            "💡 입고·반출·효자상품·광고·순이익 등 궁금한 점을 물어보시면 한눈에 깔끔하게 요약해 드립니다!"
        ]
        facts=[{'id':'inventory.summary','label':'왓니몰 실시간 운영 요약','values':{'연결 옵션 수':len(rows),'API 판매가능재고 합계(개)':summary.get('api_stock'),'Wing 30일 판매금액(원)':summary.get('revenue30'),'입고 검토 항목':summary.get('restock'),'품절 항목':summary.get('out_of_stock')},'source_ids':['inventory','api_inventory']}]
        source_ids.update(('inventory','api_inventory'))
        gaps=['연결된 대시보드 원본 데이터를 실시간으로 참조합니다.']
    if not any((restock,decline,withdraw,ask_profit,ask_ads,ask_returns,diagnosis,catalog_all,ask_oos,ask_bestseller,ask_sales,ask_cost,ask_greeting,ask_refresh)):
        if not matches or re.search(r'수수료|정산',question): return None
        if not re.search(r'재고|판매\s*(?:량|수량|현황|금액)|입고\s*(?:예정|현황|권장)|상품\s*(?:현황|정보|상태)|옵션|어때|알려|보여|얼마나|몇\s*개|어떻게|팔리|나가|상태|현황',question) and len(question.strip())>25:
            return None
        header=f"📌 상품 현황 요약 ({len(matches)}개 옵션)"
        bullets=[]
        for row in matches[:6]:
            stock=_stock_desc(row,short=True)
            sold='미확인' if row['recent_qty'] is None else f"{row['recent_qty']:g}개"
            prev_sold=f"(직전 {row['previous_qty']:g}개)" if row.get('previous_qty') is not None else ""
            price='미확인' if row['price'] is None else f"{row['price']:,}원"
            if row['wing']:
                planned=', '.join(f"{item.get('grade') or 'NEW'} {item['stock_inbound']:g}개" for item in row['wing'] if item.get('stock_inbound') is not None) or '미확인'
            elif row.get('bundle_base_inbound') is not None:
                planned=f"모체 '{row['bundle_base_option']}' {row['bundle_base_inbound']:g}개 공유"
            else:
                planned='미확인'
            bullets.append(f"• {_short_name(row['product_name'])} / {row['option_name']} : 7일 주문 {sold}{prev_sold}, 재고 {stock}, 입고예정 {planned}, 등록 판매가 {price}")
        answer=[header,'\n'.join(bullets)]
        facts=[option_fact(row) for row in matches]
        gaps=['주문수량은 출고 이후 조회 범위입니다.']
    if not answer:
        return None
    source_ids.update(ident for fact in facts for ident in fact['source_ids'])
    if decline and not diagnosis: gaps.append('판매 목표 수량이 없어 판매 부족은 직전 7일 대비 감소로 해석했습니다.')
    if (restock or withdraw) and not diagnosis:
        source=next((item for item in snapshot.get('sources',[]) if item['id']=='inventory'),{})
        if not source.get('time'):
            gaps.append('Wing 재고 자료의 수집 시각을 확인해야 합니다.')
        if not any(row['wing'] for row in (matches or rows)):
            gaps.append('해당 범위의 Wing 재고 보고서 자료가 없습니다.')
    dedup_gaps=list(dict.fromkeys(gaps))
    dedup_sugs=list(dict.fromkeys(suggestions))[:3]
    result=make_reply(snapshot,answer,list({fact['id']:fact for fact in facts}.values()),source_ids,dedup_gaps,['지금 부족하거나 보완해야 할 점이 뭐야?','이번 주 안에 추가 입고를 검토할 상품은 뭐야?','재고를 빼야 할 상품은 뭐야?','잘 팔리는 효자 상품 순위 알려줘'],suggestions=dedup_sugs)
    families={row['product_id'] or row['product_name'] for row in matches}
    if len(families)==1:
        result['operations_option_ids']=[row['option_id'] for row in matches]
    elif (decline or restock or withdraw):
        oids=[str(f['values'].get('옵션 ID')) for f in facts if f.get('id','').startswith('operations.') and f.get('values',{}).get('옵션 ID')]
        if oids: result['operations_option_ids']=oids
    return result
