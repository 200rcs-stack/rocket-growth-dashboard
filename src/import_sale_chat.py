"""Conversation calculator for selling an imported lot under explicit assumptions."""
import re
from decimal import Decimal

from config import now
from src.import_cost_chat import NUMBER, basis_input, calculation, coefficient, compact, decimal, fmt, fx_input, inline_input, memory_values, named_records, won
from src.product_prices import listing_price, matching_prices, price_fact, requested_ids, similar_product_names


PROFIT = r'순\s*이익|손익|마진|얼마(?:나)?(?:\s*정도)?\s*(?:남|벌)'
SALE_QUANTITY = rf'{NUMBER}\s*개\s*(?:를\s*)?(?:다\s*|전부\s*|모두\s*)?(?:판매|팔)'
MONEY = rf'(?<![+\-\d.,]){NUMBER}\s*(만)?\s*원'
PRICE = rf'(?:판매가|판매\s*단가)\s*(?:는|은|이|[:=])?\s*(?:개당\s*)?{MONEY}|{MONEY}\s*에\s*(?:팔|판매)'
UNIT_PRICE = rf'(?:개당|한\s*개에)\s*{MONEY}'
OTHER_COST = rf'(?:수수료|물류비|배송비|광고비|원가|환율|판매\s*비용)\s*(?:는|은|이|가|[:=])?\s*(?:개당\s*)?{MONEY}'


def money_input(pattern, question):
    match=re.search(pattern,question)
    if not match:
        return None
    groups=match.groups()
    for i in range(0,len(groups),2):
        if groups[i] is None:
            continue
        value=decimal(groups[i])*(10000 if groups[i+1] else 1)
        return int(value) if 0<=value<=10**11 and value==int(value) else None
    return None


def sale_reply(snapshot, question, history, records):
    asking_profit=bool(re.search(PROFIT,question))
    recent=next((turn for turn in reversed(history or []) if turn.get('state','complete')=='complete'),{})
    previous=recent.get('reply') or {}
    prior=previous.get('import_cost_context')
    prior_sale=previous.get('import_sale_context')
    selected=named_records(question,records)
    quantity_match=re.search(SALE_QUANTITY,question)
    all_units=bool(re.search(r'(?:다|전부|모두)\s*(?:팔|판매)|완판',question))
    # Strip other cost clauses before interpreting an unqualified “개당 ...원”.
    price=money_input(PRICE,question)
    if price is None:
        price=money_input(UNIT_PRICE,re.sub(OTHER_COST,' ',question))
    total_cost=money_input(rf'(?:총\s*판매\s*비(?:용)?|판매\s*비(?:용)?\s*(?:합계|총액)|쿠팡\s*비용\s*(?:합계|총액))\s*(?:은|이|는|[:=])?\s*{MONEY}',question)
    fx=fx_input(question)
    freight=re.search(r'(?:중국\s*물류비|물류비|내륙\s*운송비|운송비|\d+(?:\.\d+)?\s*위안(?:은|이))[^,.!?\n]{0,26}?(?:전체|총액|합계|개당|개별)',question)
    basis=basis_input(freight[0]) if freight else None
    ids=requested_ids(question)
    name_confirmation=re.search(r'등록상품명\s*(?:은|이|는|[:=])?\s*["“]?([^"”\n,.!?]+)',question)
    confirmed_name=re.sub(r'\s*(?:이야|입니다|이에요|맞아요|맞아)\s*$','',name_confirmation[1]).strip() if name_confirmation else ''
    followup=prior_sale and (price is not None or total_cost is not None or fx is not None or basis or quantity_match or ids or confirmed_name)
    if not (followup or (asking_profit and (quantity_match or all_units or price is not None))):
        return None
    inline=inline_input(question)
    record=inline or (selected[0] if len(selected)==1 else None)
    if inline and len(selected)==1:
        record={**record,'name':selected[0]['name']}
    # Use the preceding import lot only for an unqualified follow-up. An explicit
    # request about another product must not inherit the previous product's costs.
    residual=re.sub(SALE_QUANTITY+r'|'+PRICE+r'|'+UNIT_PRICE, ' ', question)
    residual=re.sub(r'(?:팔면|팔았을\s*때|팔았을때|판매하면|판매했을\s*때|판매\s*기준|완판하면|완판\s*시|(?:다|전부|모두)\s*(?:팔면|판매하면))',' ',residual)
    generic_question=bool(re.fullmatch(r'(?:[\s,.!?~]|그럼|그러면|그리고|면|하면|았을\s*때|했을\s*때|가정하면|예상|대략|정도|은|는|이|이야|얼마|정도야|될까|돼|될지|나와|나올까|알려\s*줘|계산해\s*줘|남아|남을까|벌어|'+PROFIT+r')*',residual))
    parameter_only=bool(re.match(r'\s*(?:(?:그럼|그리고)\s*)?(?:판매가|판매\s*단가|개당|한\s*개에|(?:실제\s*)?(?:적용\s*)?환율|(?:중국\s*)?물류비|(?:수입비\s*외\s*)?(?:총\s*판매\s*비(?:용)?|판매\s*비(?:용)?\s*(?:합계|총액)|쿠팡\s*비용))',question))
    if not record and prior and not selected and (generic_question or (followup and not asking_profit and (parameter_only or ids or confirmed_name))):
        record=prior
    if not record:
        if not (asking_profit and (quantity_match or all_units)):
            return None
        stamp=now().isoformat()
        return {'answer':'예상 이익은 판매대금에서 판매한 수량에 해당하는 수입비와 판매비를 뺀 금액입니다. 어느 상품을 몇 원에 판매하는지 알려 주시면, 해당 상품 원가를 확인해서 계산할 수 있습니다.',
                'facts':[],'sources':[],'suggestions':[],'followups':[],'uncertainties':['계산할 상품과 개당 실제 판매가를 확인해야 합니다.'],
                'context_at':stamp,'snapshot_at':snapshot.get('generated_at'),'coverage':{'sources':0,'records':0,'uncollected_scopes':1},
                'model':'판매 손익 계산기','answer_origin':'계산에 필요한 값 확인'}
    same_record=bool(prior and compact(prior['name'])==compact(record['name']) and prior['quantity']==record['quantity'] and not inline)
    previous_values=prior_sale if same_record and prior_sale else {}
    record=dict(record)
    if same_record and record.get('exchange_rate') is None:
        record['exchange_rate']=prior.get('exchange_rate')
    if same_record and record['freight_basis']=='unknown':
        record['freight_basis']=prior['freight_basis']
    if fx is not None: record['exchange_rate']=float(fx)
    if basis: record['freight_basis']=basis
    count=decimal(quantity_match[1]) if quantity_match else decimal(record['quantity'] if all_units else previous_values.get('quantity',record['quantity']))
    if not 0<count<=10**8 or count!=int(count):
        return None
    if price is None and previous_values.get('price_basis','사용자 입력')=='사용자 입력':
        price=previous_values.get('price')
    price_basis='사용자 입력' if price is not None else None
    prior_option_ids=previous_values.get('option_ids',[])
    lookup=question if ids or confirmed_name or not prior_option_ids else question+' '+' '.join('옵션 ID '+value for value in prior_option_ids)
    subject=confirmed_name or record['name']
    api_price=None if price is not None else listing_price(snapshot,subject,lookup)
    if api_price:
        price=api_price['amount']
        price_basis='쿠팡 API '+api_price['basis']
    if total_cost is None and previous_values.get('quantity')==int(count) and previous_values.get('price')==price:
        total_cost=previous_values.get('selling_cost')
    revenue=count*price if price is not None else None
    name=record['name']
    lines=[f'{name} {fmt(count)}개 판매를 가정했습니다. '+(f'판매대금은 {won(decimal(price))} × {fmt(count)}개 = {won(revenue)}입니다.' if price is not None else f'판매대금은 개당 실제 판매가 × {fmt(count)}개입니다.')]
    if api_price:
        lines.append(f"{price_basis}을 적용했습니다. 옵션은 {', '.join(row['option_name'] for row in api_price['rows'][:4])}입니다. 조회 시각과 최근 주문 단가는 아래 근거에 표시됩니다.")
    if price is None or record.get('exchange_rate') is None:
        lines.append('판매가와 적용 환율이 모두 확인되면 원화 잔액을 계산할 수 있습니다.')
    gaps=[]
    if price is None:
        matched=matching_prices(snapshot,subject,lookup)
        if matched:
            gaps.append('등록 옵션별 가격이나 묶음 수량이 달라 적용할 단품 옵션을 확인해야 합니다. 옵션명이나 옵션 ID를 알려 주세요.')
        elif snapshot.get('product_prices'):
            similar=similar_product_names(snapshot,subject)
            lines.append(f'쿠팡 로켓그로스 등록상품에서 “{subject}”과 일치하는 상품을 찾지 못했습니다.'+(' 비슷한 이름으로 조회되는 상품은 '+', '.join(similar)+'입니다.' if similar else ''))
            gaps.append('운영 메모와 쿠팡 가격을 연결하려면 등록상품명 또는 옵션 ID를 알려 주세요.')
        else:
            gaps.append('공식 옵션 판매가 자료가 아직 없습니다. 개당 실제 판매가를 입력하면 그 값으로 계산할 수 있습니다.')
    if record.get('exchange_rate') is None: gaps.append('송금·카드 내역의 위안당 적용 환율을 알려 주세요.')
    if record['freight_basis']=='unknown': gaps.append(f"중국 물류비 {fmt(decimal(record['freight_cny']))}위안이 수입 건 전체인지, 개당인지 확인해 주세요.")
    if total_cost is None: gaps.append('최종 잔액을 보려면 수입비 외에 이 수량의 쿠팡 수수료·로켓그로스 비용·광고비·반품 등 판매비 합계가 필요합니다.')
    values={'가정 판매 수량(개)':int(count),'계산에 쓴 개당 판매가(원)':price,'판매가 기준':price_basis,'예상 판매대금(원)':int(revenue) if revenue is not None else None,'입력한 판매 관련 비용 합계(원)':total_cost}
    if count>record['quantity']:
        gaps.append(f"운영 메모에 원가가 있는 수량은 {record['quantity']:,}개입니다. 초과분의 원가가 필요합니다.")
    else:
        for scenario in calculation(record):
            label='중국 물류비가 수입 건 전체라면' if scenario['basis']=='lot' else '중국 물류비가 개당이라면'
            if 'cash_per_unit' not in scenario:
                lot_count=decimal(record['quantity'])
                import_formula=f"{coefficient(decimal(record['tax_krw'])*count,lot_count)}원 + {coefficient(scenario['cny_total']*count,lot_count)} × 적용 환율"
                lines.append(f'{label}, {fmt(count)}개에 배분한 수입비는 {import_formula}입니다. 이 금액과 판매비를 판매대금에서 빼면 됩니다.')
                continue
            import_cost=scenario['cash_per_unit']*count
            if revenue is None:
                lines.append(f'{label}, {fmt(count)}개에 배분한 수입비는 약 {won(import_cost)}입니다.')
                continue
            amount=revenue-import_cost-(total_cost if total_cost is not None else 0)
            stage='입력 비용 반영 후 예상 잔액' if total_cost is not None else '판매비 차감 전 예상 잔액'
            values[label+' · '+stage]=won(amount)
            lines.append(f'{label}, 수입비 약 {won(import_cost)}를 반영한 {stage}은 약 {won(amount)}입니다.')
    stamp=now().isoformat()
    note='관세와 수입 부가세 납부액을 함께 뺀 현금 기준 추정입니다. 미입력 비용과 세금 조정에 따라 실제 순이익은 달라집니다.'
    facts=[{'id':'user.import.sale','label':'판매 시나리오 · 계산 조건','values':values,'source_ids':['user_import']},
           {'id':'user.import.calc','label':'수입 건 원가','values':memory_values(record),'source_ids':['user_import']}]
    sources=[{'id':'user_import','name':'운영 메모와 대화 입력값','scope':'상품별 가정 판매 손익','status':'입력 조건 기준','time':record.get('updated_at')}]
    if api_price:
        facts.extend(price_fact(row,f'price.sale.{i}') for i,row in enumerate(api_price['rows'][:6]))
        sources.extend(source for source in snapshot.get('sources',[]) if source['id'] in ('api_prices','api_orders'))
    option_ids=[row['option_id'] for row in api_price['rows']] if api_price and (ids or prior_option_ids or confirmed_name) else []
    return {'answer':'\n\n'.join(lines),'facts':facts,'sources':sources,
            'data_note':note,'suggestions':[],'uncertainties':gaps or [note],'followups':[],
            'context_at':stamp,'snapshot_at':snapshot.get('generated_at'),'coverage':{'sources':len(sources),'records':len(facts),'uncollected_scopes':len(gaps)},
            'model':'판매 손익 계산기 · API 미사용','answer_origin':'상품별 예상 판매 손익 계산',
            'import_cost_context':{k:v for k,v in record.items() if k!='updated_at'},'import_sale_context':{'quantity':int(count),'price':price,'price_basis':price_basis,'selling_cost':total_cost,'option_ids':option_ids}}
