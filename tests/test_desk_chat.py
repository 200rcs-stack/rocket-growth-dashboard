import json
from unittest.mock import Mock
import pytest
from src import desk_chat as chat


def snapshot():
    return {'summary':{'revenue30':100,'sold30':None},'generated_at':'2026-10-27T12:00:00+09:00',
            'sources':[{'id':'inventory','name':'재고 엑셀','time':'2020-01-01T00:00:00+09:00'}],
            'inventory':[{'product_name':'원본 상품','option_id':'1','stock_available':5,'unit_cost':None,'password':'must-not-leak'}],
            'returns':[{'product_name':'상품','option_id':'1','process_status':'회수중','reason':'단순변심','customer_name':'must-not-leak','order_no':'must-not-leak'}]*2,
            'finance':[{'revenue':20,'expenses':-30,'profit':-10,'start':'2026-10-01'}],
            'ad_products':[{'product':'광고 상품','spend':4,'sales_14d':8}],
            'gaps':[{'name':'미출고 주문','reason':'미연결'}]}


def payload():
    return {'answer':'두 금액은 상품 범위와 집계 기준이 다릅니다.','fact_ids':['sales.excel','sales.api','sales.difference'],
            'suggestions':['같은 옵션과 기간의 원본을 대조하세요.'],'uncertainties':['차액의 취소·환불 연결은 미확인입니다.'],'followups':['어느 옵션에서 차이가 나나요?']}


def setup(monkeypatch,result=None):
    monkeypatch.setattr(chat,'env_key',lambda k:'test-key' if k=='OPENAI_API_KEY' else None)
    response=Mock(status_code=200)
    response.json.return_value={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(result or payload())}]}]}
    post=Mock(return_value=response);monkeypatch.setattr(chat.requests,'post',post)
    return post


def test_context_covers_connected_data_preserves_missing_values_and_blocks_identifiers():
    result=chat.context(snapshot())
    catalog={f['id']:f for f in result['catalog']}
    assert catalog['inventory.0']['values']['매입원가(원)'] is None
    assert catalog['finance.0']['values']['revenue']==20
    assert catalog['ad_products.0']['values']['광고비(원)']==4
    assert catalog['returns.group.0']['values']['접수 건수']==2
    assert result['sources'][0]['review_required'] is True
    assert result['gaps'][0]['name']=='미출고 주문'
    assert 'must-not-leak' not in json.dumps(result)


def test_grounded_reply_uses_program_facts_and_recent_history(monkeypatch):
    post=setup(monkeypatch)
    result=chat.answer(snapshot(),'왜 다른가요?',[{'question':'앞선 질문','reply':{'answer':'앞선 답변'}}]*12)
    assert result['facts'][0]['values']['금액(원)']==100
    request=post.call_args_list[0].kwargs['json']
    assert request['store'] is False
    assert len(json.loads(request['input'])['previous_conversation'])==8
    assert result['sources'][0]['review_required'] is True
    assert result['coverage']['uncollected_scopes']==1
    assert post.call_count==2
    assert result['verification']=='근거 대조 검토 완료'


def test_fabricated_facts_fail_closed(monkeypatch):
    p=payload();p.update(fact_ids=['invented.fact']);setup(monkeypatch,p)
    with pytest.raises(RuntimeError,match='근거 검증'):chat.answer(snapshot(),'질문')


def test_unverified_numbers_leave_only_known_evidence(monkeypatch):
    p=payload();p.update(answer='확정 매출은 999999원입니다.')
    post=setup(monkeypatch,p)
    result=chat.answer(snapshot(),'판매금액 알려줘')
    assert post.call_count==2
    assert '999999' not in result['answer']
    assert result['facts'][0]['values']['금액(원)']==100


def test_reviewed_references_render_exact_source_values(monkeypatch):
    p=payload();p.update(answer='재고 보고서에는 [[sales.excel|금액(원)]]원이 표시됩니다.',suggestions=['예상 이익은 999999원입니다.'])
    setup(monkeypatch,p)
    result=chat.answer(snapshot(),'판매금액 알려줘')
    assert '100원' in result['answer']
    assert '999999' not in str(result)


def test_api_failures_expose_no_provider_response_or_secret(monkeypatch):
    post=setup(monkeypatch);post.return_value.status_code=401
    post.return_value.json.return_value={'error':{'message':'secret provider detail'}}
    with pytest.raises(RuntimeError) as error:chat.answer(snapshot(),'질문')
    assert 'secret' not in str(error.value) and 'test-key' not in str(error.value)


def test_oversize_question_never_calls_model(monkeypatch):
    post=setup(monkeypatch)
    with pytest.raises(ValueError):chat.answer(snapshot(),'x'*2001)
    post.assert_not_called()


def test_critical_revenue_explanation_cannot_invent_a_refund_cause(monkeypatch):
    p=payload();p['answer']='음수는 반품 처리 때문입니다.'
    setup(monkeypatch,p)
    result=chat.answer(snapshot(),'판매금액 차이가 뭐야?')
    assert '음수의 거래 원인은 확인되지 않았으므로 환불이나 취소로 해석하지 않습니다' in result['answer']
    assert '반품 처리 때문' not in result['answer']
    assert result['answer_origin'].startswith('검증된 집계 기준')


def test_product_cost_analysis_is_included_in_chat_without_extra_sensitive_fields():
    source=snapshot()
    source['cost_analysis']={'total':2,'entered':1,'matched':1,'gross':100,'full':False,'note':'기타 비용 전','rows':[{'product_name':'원가 상품','unit_cost':20,'gross_difference':100,'customer_name':'must-not-leak'}]}
    facts={f['id']:f for f in chat.context(source)['catalog']}
    assert facts['cost.analysis']['values']['계산 가능 항목 원가 차감 금액·기타 비용 전(원)']==100
    assert facts['cost.product.0']['values']['매입원가(원)']==20
    assert 'must-not-leak' not in json.dumps(facts)


TENT={'name':'비상용 텐트','quantity':100,'unit_cny':7.5,'tax_krw':50000,'freight_cny':20,'freight_basis':'unknown','approximate_freight':True,'exchange_rate':None}


def test_sell_through_question_reuses_the_previous_lot_and_later_selling_inputs(monkeypatch):
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('calculator must not call model')))
    cost=chat.answer(snapshot(),'비상용 텐트 수입 원가 계산해줘',memory=[TENT])
    history=[{'state':'complete','reply':cost}]
    first=chat.answer(snapshot(),'순이익은 대략 얼마정도 돼? 100개 다 팔면',history,[TENT])
    assert '비상용 텐트 100개' in first['answer']
    assert '50,000원 + 770 × 적용 환율' in first['answer']
    assert '50,000원 + 2,750 × 적용 환율' in first['answer']
    assert first['import_sale_context']['price'] is None
    history.append({'state':'complete','reply':first})
    second=chat.answer(snapshot(),'판매가 9,900원, 환율 200원, 중국 물류비는 전체 기준이야',history,[TENT])
    assert '990,000원' in second['answer'] and '786,000원' in second['answer']
    assert '판매비 차감 전' in second['answer']
    assert second['import_sale_context']['selling_cost'] is None
    history.append({'state':'complete','reply':second})
    third=chat.answer(snapshot(),'판매 비용 합계 10만원이야',history,[TENT])
    assert '686,000원' in third['answer'] and '입력 비용 반영 후' in third['answer']
    assert TENT['exchange_rate'] is None


def test_different_product_does_not_inherit_the_previous_import_memo(monkeypatch):
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('missing product must ask before calculating')))
    result=chat.answer(snapshot(),'등산화 100개 팔면 순이익 얼마야?', [{'reply':{'import_cost_context':TENT}}],[TENT])
    assert '어느 상품' in result['answer'] and '비상용 텐트' not in result['answer']


def test_sale_uses_matching_api_price_without_confusing_similar_items_or_packs(monkeypatch):
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('prices should use official evidence directly')))
    source=snapshot()
    source['product_prices']=[{'product_id':'123456789','product_name':'비상 생존침낭','option_id':'987654321',
                              'option_name':'1개 녹색','units_per_option':1,'sale_price':7900,'latest_order_price':7600},
                             {'product_id':'123456789','product_name':'비상 생존침낭','option_id':'987654322',
                              'option_name':'2개 녹색','units_per_option':2,'sale_price':14450,'latest_order_price':14000}]
    price=chat.answer(source,'비상 생존침낭 1개 녹색 판매가 알려줘')
    assert '7,900원' in price['answer'] and '14,450원' not in price['answer']
    history=[{'reply':{'import_cost_context':TENT}}]
    initial=chat.answer(source,'순이익은 대략 얼마정도 돼? 100개 다 팔면',history,[TENT])
    assert '일치하는 상품을 찾지 못했습니다' in initial['answer'] and initial['import_sale_context']['price'] is None
    matched=chat.answer(source,'옵션 ID 987654321이야',[{'reply':initial}],[TENT])
    assert matched['import_sale_context']['price']==7900 and '790,000원' in matched['answer']
    followup=chat.answer(source,'환율 200원, 중국 물류비는 전체야',[{'reply':matched}],[TENT])
    assert '586,000원' in followup['answer']
    assert followup['import_sale_context']['option_ids']==['987654321']


def test_import_chat_calculates_question_and_followup_without_model(monkeypatch):
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('calculator must not read API key')))
    question='비상용 텐트 매원원가 7.5위안 이고 100개 수입할때 관세,부가세 합해서 5만원 냈어 중국 물류비는 20위안 정도 되구'
    first=chat.answer(snapshot(),question,memory=[TENT])
    assert '770위안' in first['answer'] and '2,750위안' in first['answer']
    assert '500원 + 7.7 ×' in first['answer'] and '500원 + 27.5 ×' in first['answer']
    assert '원화 금액을 확정할 수 없습니다' in first['uncertainties'][0]
    second=chat.answer(snapshot(),'물류비 전체 기준이고 적용 환율은 200원',[{'state':'complete','reply':first}],[TENT])
    assert '2,040원' in second['answer'] and '204,000원' in second['answer']
    assert '2,750위안' not in second['answer'] and TENT['exchange_rate'] is None


def test_named_import_memory_remains_available_without_chat_history(monkeypatch):
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('calculator must not read API key')))
    answer=chat.answer(snapshot(),'비상용 텐트 수입 원가 계산해줘',memory=[TENT])
    assert '770위안' in answer['answer']
    assert answer['sources'][0]['name']=='운영 메모 · 사용자 직접 입력'
    facts={f['id']:f for f in chat.context(snapshot(),[TENT])['catalog']}
    assert facts['user.import.0']['values']['관세·수입 부가세 납부 합계(원)']==50000


def test_question_with_no_matching_evidence_can_ask_for_more(monkeypatch):
    p=payload();p.update(fact_ids=[],answer='이 상품의 정확한 옵션명을 알려 주세요.')
    setup(monkeypatch,p)
    assert chat.answer(snapshot(),'처음 듣는 상품의 마진이 뭐야?')['facts']==[]


def test_recalling_an_earlier_question_uses_history_as_history(monkeypatch):
    p=payload();p.update(fact_ids=['dialog.history.0'],answer='이전에는 텐트 수입비의 물류비 기준을 물으셨어요.')
    post=setup(monkeypatch,p)
    old={'question':'비상용 텐트 중국 물류비 20위안은 어떻게 계산해?', 'created_at':'2026-10-01T09:00:00+09:00'}
    result=chat.answer(snapshot(),'비상용 텐트 수입 원가를 전에 어떤 조건으로 이야기했고, 지금 운영 메모 기준으로 무엇을 확인해야 해?',related_history=[old])
    assert result['facts'][0]['values']['질문']==old['question']
    assert result['related_questions']==[{'question':old['question'],'asked_at':old['created_at']}]
    for call in post.call_args_list:
        assert json.loads(call.kwargs['json']['input'])['related_earlier_conversation'][0]['question']==old['question']


def test_recall_keeps_original_questions_when_model_invents_a_number(monkeypatch):
    p=payload();p.update(answer='확정 원가는 999999원입니다.',fact_ids=['dialog.history.0'])
    post=setup(monkeypatch,p)
    old={'question':'비상용 텐트 중국 물류비 20위안은 어떻게 계산해?', 'created_at':'2026-10-01T09:00:00+09:00'}
    result=chat.answer(snapshot(),'비상용 텐트 원가와 판매 마진을 전에 뭐라고 했어?',memory=[TENT],related_history=[old])
    assert post.call_count==2
    assert result['related_questions'][0]['question']==old['question']
    assert '999999' not in result['answer'] and '770위안' in result['answer']
    post.reset_mock()
    result=chat.answer(snapshot(),'비상용 텐트 원가 전에 뭐라고 했어?',memory=[TENT],related_history=[old])
    assert '770위안' in result['answer'] and result['related_questions'][0]['question']==old['question']
    post.assert_not_called()
