"""Safe Rocket Growth option prices, kept distinct from observed order prices."""
import re
from decimal import Decimal, InvalidOperation


def option_id(value):
    return str(value) if re.fullmatch(r'\d+',str(value)) else None


def positive_amount(value):
    try:
        amount=Decimal(str(value))
        return int(amount) if amount.is_finite() and 0<amount<=10**10 and amount==int(amount) else None
    except InvalidOperation:
        return None


def project_detail(product, detail, captured_at):
    product_id=option_id(product['sellerProductId'])
    if not isinstance(detail,dict) or option_id(detail.get('sellerProductId'))!=product_id or not isinstance(detail.get('items'),list):
        raise ValueError('상품 상세 ID 또는 옵션 목록 불일치')
    options=[]
    for item in detail['items']:
        rg=item.get('rocketGrowthItemData') or {}
        ident=option_id(rg.get('vendorItemId'))
        if not ident: continue
        prices=rg.get('priceData') or {}
        name=str(item.get('itemName') or '')
        # The seller's explicit pack label distinguishes one imported piece
        # from a listing that sells several together.
        packs=re.findall(r'(?<!\d)(\d+)\s*(?:개(?!입)|박스)',name)
        options.append({'option_id':ident,'option_name':name,'sale_price':positive_amount(prices.get('salePrice')),
                        'units_per_option':int(packs[-1]) if packs else (1 if name.strip() in ('단품','단일상품') else None)})
    return {'product_id':product_id,'product_name':str(product['sellerProductName']),
            'display_name':str(detail.get('displayProductName') or ''),'general_name':str(detail.get('generalProductName') or ''),
            'inbound_name':str((detail.get('additionalInformation') or {}).get('rfmInboundName') or ''),
            'captured_at':captured_at,'options':options}


def order_price_evidence(orders):
    latest={}
    for order in orders:
        paid=order['paidAt']
        for item in order['orderItems']:
            ident=option_id(item['vendorItemId'])
            amount=positive_amount(item['unitSalesPrice'])
            if not ident or amount is None: continue
            previous=latest.get(ident)
            if previous is None or paid>previous[0]: latest[ident]=(paid,{amount})
            elif paid==previous[0]: previous[1].add(amount)
    return {ident:(paid,next(iter(amounts))) for ident,(paid,amounts) in latest.items() if len(amounts)==1}


def price_rows(api):
    last_paid=order_price_evidence(api.get('orders',[]))
    rows=[]
    for detail in (api.get('product_details') or {}).values():
        for option in detail['options']:
            paid,amount=last_paid.get(option['option_id'],(None,None))
            rows.append({**option,**{k:detail[k] for k in ('product_id','product_name','display_name','general_name','inbound_name','captured_at')},
                         'latest_order_price':amount,'latest_order_paid_ms':paid,'retained':bool(detail.get('retained'))})
    return rows


def normalized(value):
    return re.sub(r'[^가-힣a-z0-9]','',str(value or '').casefold())


def names(row):
    return [row.get(key) or '' for key in ('product_name','display_name','general_name','inbound_name')]


def requested_ids(question):
    return set(re.findall(r'(?:옵션\s*(?:ID|번호)?|등록상품\s*(?:ID|번호)?|vendorItemId|sellerProductId)\s*[:=]?\s*(\d{7,})(?!\d)',question,re.I))


_KOR_PACKS = {'한개':'1개','두개':'2개','세개':'3개','네개':'4개','다섯개':'5개','단품':'1개','단일':'1개'}


def _opt_tokens(text):
    clean=normalized(text)
    for k,v in _KOR_PACKS.items():
        clean=clean.replace(k,v)
    tokens=set(re.findall(r'\d+개|\d+ml|\d+l|\d+g|\d+kg|\d+p|\d+정|\d+캡슐|\d+박스|[가-힣]{2,}|[a-z]{2,}',str(text or '').casefold()))
    for k,v in _KOR_PACKS.items():
        if k in clean: tokens.add(v)
    return tokens-{'옵션','상품','제품','기준','정리','추천','사이즈','타입'}


def matching_prices(snapshot, subject, question):
    rows=snapshot.get('product_prices') or []
    ids=requested_ids(question)
    if ids: return [row for row in rows if row['option_id'] in ids or row['product_id'] in ids]
    norm_q=normalized(question)
    for k,v in _KOR_PACKS.items():
        norm_q=norm_q.replace(k,v)
    variants=[row for row in rows if len(normalized(row['option_name']))>=3 and normalized(row['option_name']) in norm_q]
    query=normalized(subject)
    for k,v in _KOR_PACKS.items():
        query=query.replace(k,v)
    if variants:
        for variant in {normalized(row['option_name']) for row in variants}:
            query=query.replace(variant,'')
    if len(query)<2: return []
    matched=[row for row in rows if any(query in normalized(name) for name in names(row))]
    if not matched: return []
    if variants:
        chosen=[row for row in matched if row in variants]
        if chosen: return chosen
    scored=[]
    for row in matched:
        opt_tokens=_opt_tokens(row['option_name'])
        hits=[tok for tok in opt_tokens if normalized(tok) in norm_q]
        if hits:
            scored.append((len(hits),sum(len(normalized(t)) for t in hits),row))
    if scored:
        top_count=max(x[0] for x in scored)
        top_len=max(x[1] for x in scored if x[0]==top_count)
        return [x[2] for x in scored if x[0]==top_count and x[1]==top_len]
    return matched


def similar_product_names(snapshot, subject):
    terms={re.sub(r'용$','',word) for word in re.findall(r'[가-힣a-zA-Z]{2,}',subject)}-{'상품','제품','우리','가격'}
    return list(dict.fromkeys(row['product_name'] for row in snapshot.get('product_prices',[])
                              if any(len(term)>=2 and term in row['product_name'] for term in terms)))[:3]


def listing_price(snapshot, subject, question):
    matched=matching_prices(snapshot,subject,question)
    if len({row['product_id'] for row in matched})!=1: return None
    singles=[row for row in matched if row.get('units_per_option')==1]
    if not singles: return None
    prices={row.get('sale_price') for row in singles}
    if len(prices)==1 and None not in prices:
        return {'amount':next(iter(prices)),'basis':'등록 판매가','rows':singles}
    if prices=={None}:
        prices={row.get('latest_order_price') for row in singles}
        if len(prices)==1 and None not in prices:
            return {'amount':next(iter(prices)),'basis':'최근 주문 단가','rows':singles}
    return None


def price_fact(row, ident):
    values={'등록상품명':row['product_name'],'옵션명':row['option_name'],'옵션 ID':row['option_id'],
            '등록 판매가(원)':row.get('sale_price'),'등록가 조회 시각':row.get('captured_at'),
            '최근 주문 단가(원)':row.get('latest_order_price'),'주문 결제 시각':row.get('latest_order_paid_at'),
            '옵션 구성 수량':row.get('units_per_option')}
    if row.get('retained'): values['조회 상태']='최근 상세 갱신 실패 · 이전 검증값'
    sources=['api_prices'] if row.get('sale_price') is not None else []
    if row.get('latest_order_price') is not None: sources.append('api_orders')
    return {'id':ident,'label':'쿠팡 API · 옵션 가격','values':values,'source_ids':sources}
