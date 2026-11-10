"""Calculate import cash outlay from seller input, separate from SKU accounting."""
import re
from decimal import Decimal, ROUND_HALF_UP

from config import now

NUMBER = r'(\d+(?:,\d{3})*(?:\.\d+)?)'
FX = rf'(?:실제\s*)?(?:적용\s*)?환율\s*(?:은|이|[:=])?\s*{NUMBER}\s*원|(?:1\s*)?위안\s*당\s*{NUMBER}\s*원|{NUMBER}\s*원\s*/\s*위안'


def compact(text):
    return re.sub(r'\s+', '', text).casefold()


def decimal(value):
    return Decimal(str(value).replace(',', ''))


def fmt(value):
    return format(value, ',.2f').rstrip('0').rstrip('.')


def coefficient(total, quantity):
    part=total/quantity
    return fmt(part) if decimal(fmt(part)) == part else f'({fmt(total)} ÷ {fmt(quantity)})'


def won(value):
    return f'{value.quantize(Decimal(1), rounding=ROUND_HALF_UP):,}원'


def fx_input(question):
    match = re.search(FX, question)
    if not match:
        return None
    value = decimal(next(v for v in match.groups() if v is not None))
    return value if 0 < value <= 10000 else None


def inline_input(question):
    # Each amount is matched by its own label, never by its order in the text.
    unit = re.search(rf'(?:매입\s*원가|매원\s*원가|개당\s*원가|단가)\s*(?:는|은|이|[:=])?\s*{NUMBER}\s*(?:위안|CNY)', question, re.I)
    qty = re.search(rf'{NUMBER}\s*개\s*(?:를\s*)?(?:수입|발주|구매)', question)
    tax = re.search(rf'(?:관세[^\n.?!]{{0,28}}?부가세|부가세[^\n.?!]{{0,28}}?관세|통관\s*세금)[^\n.?!\d+\-]{{0,22}}{NUMBER}\s*(만)?\s*원', question)
    freight = re.search(rf'(?:중국\s*)?(?:물류비|운송비|배송비)\s*(?:는|은|가|[:=])?\s*(?:(?:총|개당|전체|약|대략)\s*){{0,2}}{NUMBER}\s*(?:위안|CNY)', question, re.I)
    if not all((unit, qty, tax, freight)):
        return None
    quantity = decimal(qty[1]); unit_cny = decimal(unit[1]); freight_cny = decimal(freight[1]); tax_krw = decimal(tax[1]) * (10000 if tax[2] else 1)
    if not (1 <= quantity <= 10**8 and quantity == int(quantity) and 0 <= unit_cny <= 10**8 and 0 <= freight_cny <= 10**8 and 0 <= tax_krw <= 10**10 and tax_krw == int(tax_krw)):
        return None
    freight_text = question[max(0, freight.start()-4):freight.end()+10]
    return {'name':'질문에 입력한 수입 건','quantity':int(quantity),'unit_cny':float(unit_cny),'tax_krw':int(tax_krw),
            'freight_cny':float(freight_cny),'freight_basis':basis_input(freight_text) or 'unknown',
            'approximate_freight':any(x in freight_text for x in ('정도','약','대략')),'exchange_rate':float(rate) if (rate:=fx_input(question)) is not None else None}


def basis_input(text):
    unit=bool(re.search(r'개당|개별|한\s*개당|개\s*기준',text))
    lot=bool(re.search(r'전체|총액|합계|총\s*\d|건\s*기준',text))
    return ('unit' if unit else 'lot') if unit != lot else None


def calculation(record):
    q,u,t,f=(decimal(record[k]) for k in ('quantity','unit_cny','tax_krw','freight_cny'))
    fx=decimal(record['exchange_rate']) if record.get('exchange_rate') is not None else None
    basis=record['freight_basis']
    choices=[basis] if basis!='unknown' else ['lot','unit']
    scenarios=[]
    for choice in choices:
        total=u*q+f*(q if choice=='unit' else 1)
        per=total/q
        scenario={'basis':choice,'cny_total':total,'krw_per_unit':t/q,'cny_per_unit':per,
                  'formula':f'{coefficient(t,q)}원 + {coefficient(total,q)} × 적용 환율(원/위안)'}
        if fx is not None:
            scenario.update(cash_total=t+total*fx,cash_per_unit=(t+total*fx)/q)
        scenarios.append(scenario)
    return scenarios


def memory_values(record):
    values={'기록명':record['name'],'매입 단가(위안/개)':record['unit_cny'],'수입 수량(개)':record['quantity'],
            '관세·수입 부가세 납부 합계(원)':record['tax_krw'],'중국 물류비(위안)':record['freight_cny'],
            '물류비 기준':{'lot':'수입 건 전체','unit':'개당','unknown':'미확인'}[record['freight_basis']],
            '중국 물류비 추정 여부':record['approximate_freight'],'적용 환율(원/위안)':record.get('exchange_rate')}
    for row in calculation(record):
        label='물류비 전체 기준' if row['basis']=='lot' else '물류비 개당 기준'
        values[label+' · 외화 합계(위안)']=float(row['cny_total'])
        values[label+' · 원화 환산식(개당)']=row['formula']
        if 'cash_per_unit' in row:
            values[label+' · 개당 현금 지출(원, 반올림)']=int(row['cash_per_unit'].quantize(Decimal(1),rounding=ROUND_HALF_UP))
    return values


def named_records(question, records):
    query=compact(question)
    exact=[r for r in records if compact(r['name']) in query]
    if exact:
        return exact
    # “텐트” can refer to “비상용 텐트”, but only with a unique result.
    words=set(re.findall(r'[가-힣a-zA-Z0-9]{2,}',question))-{'상품','수입','원가','단가','매입','비용','기준','계산','자료','물류','해줘','비상용','수입분','관세','부가세','환율','메모'}
    hits=[r for r in records if words.intersection(re.findall(r'[가-힣a-zA-Z0-9]{2,}',r['name']))]
    return hits if len(hits)==1 else []


def cost_reply(snapshot, question, history, records):
    inline=inline_input(question)
    selected=named_records(question,records)
    explicitly_cost=bool(re.search(r'원가|수입비|현금\s*지출|환율|물류비|얼마|매입|관세|부가세',question))
    analytical=bool(re.search(r'마진|순이익|손익|광고|반품|재고|판매량|매출|비교|판매가|이익률|수수료',question))
    narrow_followup=bool(re.fullmatch(r'\s*(?:(?:그럼|그리고)\s*)?(?:(?:적용|실제)\s*)?(?:환율|(?:중국\s*)?물류비|(?:전체|개당)\s*기준|개당\s*얼마|\d+(?:\.\d+)?\s*위안(?:은|이))[^\n]{0,65}',question))
    previous=next((h for h in reversed(history or []) if h.get('state','complete')=='complete'),None)
    last_cost=(previous or {}).get('reply',{}).get('import_cost_context')
    if inline and len(selected)==1:
        inline['name']=selected[0]['name']  # Keep new amounts temporary.
    changing_inputs=bool(re.search(r'(?:매입\s*원가|단가|관세|부가세|\d+\s*개\s*(?:수입|발주|구매))[^\n]{0,40}\d|\d+\s*(?:위안|CNY)\s*(?:으로|으로는|이라고|정도)',question,re.I))
    if not inline and (analytical or changing_inputs or not (explicitly_cost or narrow_followup) or (not selected and not (narrow_followup and last_cost))):
        return None
    if not inline and len(selected)>1:
        return None
    base=inline or (selected[0] if selected else last_cost)
    record={**base}
    rate=fx_input(question)
    basis=basis_input(question) if '물류비' in question or narrow_followup else None
    if rate is not None: record['exchange_rate']=float(rate)
    if basis and not inline: record['freight_basis']=basis
    transient=bool(inline or (rate is not None and record['exchange_rate']!=base.get('exchange_rate')) or record['freight_basis']!=base['freight_basis'])
    q,u,t,f=(decimal(record[k]) for k in ('quantity','unit_cny','tax_krw','freight_cny'))
    scenarios=calculation(record)
    answers=[f"{record['name']}의 상품대금은 {fmt(u)}위안 × {fmt(q)}개 = {fmt(u*q)}위안입니다. 관세·수입 부가세 {won(t)}는 개당 {won(t/q)}입니다."]
    lines=[]
    for row in scenarios:
        label='물류비가 수입 건 전체라면' if row['basis']=='lot' else '물류비가 개당이라면'
        lines.append(f"{label}: 외화 비용 합계 {fmt(row['cny_total'])}위안. 개당 {row['formula']}." + (f" 적용 환율 {fmt(decimal(record['exchange_rate']))}원으로 계산하면 개당 약 {won(row['cash_per_unit'])}, 전체 약 {won(row['cash_total'])}입니다." if 'cash_per_unit' in row else ''))
    answers.extend(lines)
    gaps=[]
    if record.get('exchange_rate') is None:gaps.append('실제 적용 환율이 없어 원화 금액을 확정할 수 없습니다. 송금·카드 내역의 적용 환율을 알려 주세요.')
    if record['freight_basis']=='unknown':gaps.append(f"중국 물류비 {fmt(f)}위안이 건 전체인지 개당인지 알려 주세요.")
    if record['approximate_freight']:gaps.append('중국 물류비는 사용자 추정액입니다.')
    gaps.append('관세와 수입 부가세의 세부 금액을 구분하지 않은 현금 지출 기준입니다. 국내 운송·통관 수수료 등 별도 비용과 쿠팡 비용은 포함하지 않았습니다.')
    if analytical:
        answers.append('이 금액은 수입 단계의 비용입니다. 판매 마진은 같은 상품·옵션의 판매가와 쿠팡 수수료·물류비 등까지 확인한 뒤 따로 계산해야 합니다.')
    timestamp=now().isoformat()
    return {'answer':'\n\n'.join(answers),'facts':[{'id':'user.import.calc','label':'사용자 입력 · 수입 현금 지출 계산','values':memory_values(record),'source_ids':['user_import']}],
            'sources':[{'id':'user_import','name':'질문에서 제공한 정보' if transient else '운영 메모 · 사용자 직접 입력','scope':'수입 건 · 쿠팡 상품에 자동 적용되지 않음','status':'증빙 대조 전','time':timestamp if transient else record.get('updated_at')}],
            'data_note':'위안 결제와 원화 납부를 합친 수입 현금 지출 계산입니다. 쿠팡 장부의 매출원가·순이익에는 자동 반영하지 않습니다.',
            'suggestions':[], 'uncertainties':gaps,'followups':[], 'context_at':timestamp,'snapshot_at':snapshot.get('generated_at'),'generated_at':timestamp,
            'coverage':{'sources':1,'records':1,'uncollected_scopes':len(gaps)},'model':'내장 수입 원가 계산기 · API 미사용','answer_origin':'입력값과 계산식으로 확인한 답변','import_cost_context':{k:v for k,v in record.items() if k!='updated_at'}}
