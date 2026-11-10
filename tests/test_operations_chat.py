from datetime import datetime

from config import KST
from src import operations_chat as operations
from src.desk_chat import answer


def test_product_questions_compare_order_windows_and_preserve_pending_inbound(monkeypatch):
    when=datetime(2026,11,9,21,tzinfo=KST)
    monkeypatch.setattr(operations,'now',lambda:when)

    def order(order_id, day, quantity):
        paid=datetime(2026,11,day,12,tzinfo=KST)
        return {'orderId':order_id,'paidAt':int(paid.timestamp()*1000),
                'orderItems':[{'vendorItemId':123456789,'salesQuantity':quantity}]}

    recent=order(2,4,3)
    api={'paid_from':'2026-10-11','paid_to':'2026-11-09','fetched_at':when.isoformat(),
         'orders':[order(1,1,8),recent,recent,order(3,9,99)]}
    windows=operations.sales_windows(api,{'123456789'})
    assert windows['options']==[{'option_id':'123456789','recent_qty':3,'previous_qty':8}]
    snapshot={'option_sales_windows':windows,
              'inventory':[{'option_id':'123456789','product_name':'비상 생존침낭','option_name':'1개 녹색','grade':'NEW',
                            'stock_available':0,'stock_inbound':100,'restock_rec_qty':26,'restock_rec_date':'2026-11-10'}],
              'api_inventory':[{'option_id':'123456789','stock':0}],
              'product_prices':[{'option_id':'123456789','product_id':'234567890','product_name':'비상 생존침낭',
                                 'option_name':'1개 녹색','sale_price':7900}]}
    decline=answer(snapshot,'판매량이 부족한 상품은 뭐야?')
    assert '8 → 3개' in decline['answer'] and 'API 재고 0개' in decline['answer']
    product=answer(snapshot,'생존침낭 녹색 1개 판매량하고 재고 알려줘')
    assert '등록 판매가 7,900원' in product['answer']
    followup=answer(snapshot,'그 상품은 이번 주에 추가 입고해야 돼?',[{'reply':product}])
    assert '기존 입고 도착일 확인' in followup['answer'] and '추가 입고 우선 검토' not in followup['answer']
    assert '권장 26개, 입고 예정 100개' in followup['answer']


def test_withdrawal_uses_inventory_age_and_order_evidence(monkeypatch):
    import src.desk_chat as chat
    from unittest.mock import Mock
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('known operations question should use source data directly')))
    row={'option_id':'123456789','product_name':'러닝 암밴드','option_name':'화이트','grade':'NEW',
         'stock_available':18,'age_61_120':0,'age_121_180':0,'age_181_plus':18,'storage_fee_mtd':810,'qty_30d':None}
    data={'inventory':[row], 'option_sales_windows':{'options':[{'option_id':'123456789','recent_qty':0,'previous_qty':0}]}}
    result=answer(data,'재고를 빼야될께 뭐야?')
    assert '반출 우선 검토 · 러닝 암밴드' in result['answer']
    assert '181일 이상 18개' in result['answer'] and '810원' in result['answer']
    assert result['facts'][0]['values']['Wing 30일 판매수량(개)'] is None
    data['option_sales_windows']['options'][0]['recent_qty']=2
    assert '반출 우선 검토 0건' in answer(data,'반출 후보 뭐야?')['answer']


def test_single_option_token_matching_handles_reversed_word_order(monkeypatch):
    import src.desk_chat as chat
    from unittest.mock import Mock
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('single option lookup must not call model')))
    snapshot={
        'option_sales_windows':{'recent_start':'2026-11-02','recent_end':'2026-11-08','previous_start':'2026-10-26','previous_end':'2026-11-01',
                                'options':[{'option_id':'95256891746','recent_qty':3,'previous_qty':6},{'option_id':'95257064468','recent_qty':1,'previous_qty':5}]},
        'inventory':[{'option_id':'95256891746','product_name':'차량 등산 낚시용 비상 생존침낭 휴대용 보온침낭','option_name':'1개 녹색','grade':'NEW','stock_available':0,'stock_inbound':100}],
        'api_inventory':[{'option_id':'95256891746','stock':0},{'option_id':'95257064468','stock':5}],
        'product_prices':[
            {'option_id':'95256891746','product_id':'111','product_name':'차량 등산 낚시용 비상 생존침낭 휴대용 보온침낭','option_name':'1개 녹색','sale_price':7900,'units_per_option':1},
            {'option_id':'95257064468','product_id':'111','product_name':'차량 등산 낚시용 비상 생존침낭 휴대용 보온침낭','option_name':'2개 녹색','sale_price':14450,'units_per_option':2},
            {'option_id':'95256891745','product_id':'111','product_name':'차량 등산 낚시용 비상 생존침낭 휴대용 보온침낭','option_name':'1개 주황색','sale_price':7900,'units_per_option':1},
        ]
    }
    res=answer(snapshot,'생존침낭 녹색 1개 옵션은 어때?')
    assert len(res['facts'])==1
    assert res['facts'][0]['values']['옵션 ID']=='95256891746'
    assert '1개 녹색' in res['answer'] and '2개 녹색' not in res['answer'] and '1개 주황색' not in res['answer']


def test_combined_operations_ads_profit_returns_diagnosis_and_catalog_without_model(monkeypatch):
    import src.desk_chat as chat
    from unittest.mock import Mock
    when=datetime(2026,11,9,21,tzinfo=KST)
    monkeypatch.setattr(operations,'now',lambda:when)
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('deterministic operations must not call model')))
    snapshot={
        'summary':{'missing_costs':40,'restock':2,'out_of_stock':1,'return_cases':181,'overdue_returns':8,'api_stock':50,'inventory_stock':48,'revenue30':818000},
        'sources':[
            {'id':'inventory','name':'재고 현황 엑셀','time':'2026-11-09T18:11:00+09:00','scope':'상품·옵션·등급','status':'수집 완료'},
            {'id':'api_inventory','name':'쿠팡 공식 API · 재고 요약','time':'2026-11-09T21:00:00+09:00','scope':'옵션별','status':'수집 완료'},
            {'id':'api_orders','name':'쿠팡 공식 API · 주문 목록','time':'2026-11-09T21:00:00+09:00','scope':'최근 30일','status':'수집 완료'},
            {'id':'ads','name':'쿠팡윙 · 광고센터','time':'2026-11-09T18:14:00+09:00','scope':'광고 요약','status':'수집 완료'},
            {'id':'ad_detail','name':'광고 보고서 엑셀','time':'2026-10-24T10:00:00+09:00','scope':'상품별 14일 전환','status':'수집 완료'},
            {'id':'finance','name':'쿠팡윙 · 수익 현황','time':'2026-11-09T19:16:00+09:00','scope':'기간별 수익','status':'수집 완료'},
            {'id':'returns','name':'반품 엑셀','time':'2026-11-09T18:12:00+09:00','scope':'반품 접수','status':'수집 완료'},
            {'id':'return_insight','name':'반품 분석 화면','time':'2026-11-09T18:15:00+09:00','scope':'월별 반품률','status':'수집 완료'},
            {'id':'compensation','name':'재고 손실 보상 엑셀','time':'2026-10-25T10:00:00+09:00','scope':'보상 내역','status':'수집 완료'},
        ],
        'option_sales_windows':{
            'recent_start':'2026-11-02','recent_end':'2026-11-08','previous_start':'2026-10-26','previous_end':'2026-11-01',
            'options':[
                {'option_id':'101','recent_qty':0,'previous_qty':0},
                {'option_id':'102','recent_qty':2,'previous_qty':6},
                {'option_id':'103','recent_qty':1,'previous_qty':5},
            ]
        },
        'inventory':[
            {'option_id':'101','product_name':'러닝 암밴드','option_name':'화이트','grade':'NEW','stock_available':18,'stock_inbound':0,'age_61_120':0,'age_121_180':0,'age_181_plus':18,'storage_fee_mtd':810,'qty_30d':0},
            {'option_id':'102','product_name':'파워핸들','option_name':'검정 LED','grade':'NEW','stock_available':0,'stock_inbound':0,'restock_rec_qty':22,'restock_rec_date':'2026-11-14','rev_30d':265200,'qty_30d':17},
            {'option_id':'103','product_name':'생존침낭','option_name':'1개 녹색','grade':'NEW','stock_available':0,'stock_inbound':100,'restock_rec_qty':26,'restock_rec_date':'2026-11-10','rev_30d':86900,'qty_30d':11},
        ],
        'api_inventory':[{'option_id':'101','stock':18},{'option_id':'102','stock':0},{'option_id':'103','stock':0},{'option_id':'104','stock':5}],
        'option_names':{'104':{'product_name':'이력 복원 상품','option_name':'복원 옵션'}},
        'product_prices':[{'option_id':'102','product_id':'202','product_name':'파워핸들','option_name':'검정 LED','sale_price':15600,'units_per_option':1}],
        'ads':{'start':'2026-11-01','end':'2026-11-08','spend':228528,'sales':662030,'roas':289.69,'captured_at':'2026-11-09T18:14:00+09:00'},
        'billing':{'month':'2026-11','eligible':225673,'promotion':0,'adjustment':0,'vat':22568,'bill':248241},
        'ad_period':{'start':'2026-10-01','end':'2026-10-23'},
        'ad_products':[{'product':'변기 청소솔','option_id':'95858893852','spend':19934,'sales_14d':0,'clicks':126,'orders_14d':0,'roas':0}],
        'finance':[{'start':'2026-10-01','end':'2026-10-31','revenue':1213020,'expenses':-1179339,'profit':53083,'ads':-732373,'fulfillment':-306533,'commission':-140433,'compensation':19402,'captured_at':'2026-11-09T19:16:00+09:00'}],
        'returns':[{'product_name':'파워핸들','option_name':'검정 LED','option_id':'102','process_status':'회수중','overdue':True,'reason':'필요없어짐','elapsed_days':95}],
        'return_insight':{'month':9,'rate':15.9,'products':40,'updated':'2026-11-08'},
        'compensation':[{'product_name':'파워핸들','option_name':'검정 LED','compensation_amount':12000}],
    }
    combined=answer(snapshot,'창고에 자리만 차지하는 쪽이랑 이번 주에 물량 채워둘 쪽을 같이 알려줘.')
    assert '추가 입고 우선 검토 · 파워핸들' in combined['answer']
    assert '반출 우선 검토 · 러닝 암밴드' in combined['answer']

    dec=answer(snapshot,'판매량 부족한 거 뭐야?')
    assert '파워핸들' in dec['answer'] and '생존침낭' in dec['answer']
    follow=answer(snapshot,'그 상품은 이번 주에 더 넣어야 해?',[{'state':'complete','reply':dec}])
    assert '추가 입고 우선 검토 · 파워핸들' in follow['answer']
    assert '기존 입고 도착일 확인 · 생존침낭' in follow['answer']

    ads_res=answer(snapshot,'지난 달 광고가 왜 비쌌고 뭐를 줄여야 해?')
    assert '-732,373원' in ads_res['answer'] and '289.69%' in ads_res['answer'] and '변기 청소솔' in ads_res['answer']

    prof_res=answer(snapshot,'지난 달 순이익?')
    assert '1,213,020원' in prof_res['answer'] and '53,083원' in prof_res['answer'] and '매출원가' in prof_res['answer']

    ret_res=answer(snapshot,'반품 접수된 거 중에 문제 있는 거 뭐야?')
    assert '회수중' in ret_res['answer'] and '15.9%' in ret_res['answer'] and '12,000원' in ret_res['answer']

    diag_res=answer(snapshot,'지금 부족하거나 보완해야 할 점이 뭐야?')
    assert '[재고·입고 보완]' in diag_res['answer'] and '[장기 재고·보관비 절감]' in diag_res['answer']

    cat_res=answer(snapshot,'우리 스토어 전체 상품이랑 재고 현황 알려줘')
    assert '전체 옵션은 4개' in cat_res['answer']
    rows={r['option_id']:r for r in operations.operations_rows(snapshot)}
    assert rows['104']['product_name']=='이력 복원 상품'

    withdraw_sales=answer(snapshot,'반출할 제품이 뭘까 ? 판매가 안되는 제품은 반출해야지')
    assert '일치하는 상품을 찾지 못했습니다' not in withdraw_sales['answer']
    assert '반출 우선 검토 · 러닝 암밴드' in withdraw_sales['answer']

    oos_res=answer(snapshot,'지금 품절된 상품 뭐 있어?')
    assert '[품절·판매중]' in oos_res['answer'] and '파워핸들' in oos_res['answer']

    best_res=answer(snapshot,'잘 팔리는 효자 상품 순위 알려줘')
    assert '1위 · 파워핸들' in best_res['answer']

    cost_res=answer(snapshot,'원가 입력 안 된 상품이 뭐야?')
    assert '매입원가 마스터 입력 현황' in cost_res['answer'] and '파워핸들' in cost_res['answer']

    # Natural phrasings & greeting resolve deterministically without calling OpenAI
    assert '권장일' in answer(snapshot,'재고를더 늘려야할 항목이 뭐야')['answer']
    assert '아르곤(Antigravity)' in answer(snapshot,'안녕 너는 이름이 뭐니?')['answer']
    assert '[재고·입고 보완]' in answer(snapshot,'현재 내가 해야될일이 뭐야')['answer']
    assert '1위 · 파워핸들' in answer(snapshot,'지난 한달동안 최고매출 효자 종목은?')['answer']


def test_multipack_bundle_options_inherit_base_unit_inventory(monkeypatch):
    import src.desk_chat as chat
    from unittest.mock import Mock
    monkeypatch.setattr(chat,'env_key',Mock(side_effect=AssertionError('bundle inventory must resolve deterministically')))
    snapshot={
        'option_sales_windows':{
            'recent_start':'2026-11-03','recent_end':'2026-11-09','previous_start':'2026-10-27','previous_end':'2026-11-02',
            'options':[
                {'option_id':'95256891746','recent_qty':2,'previous_qty':7},
                {'option_id':'95257064468','recent_qty':4,'previous_qty':23},
            ]
        },
        'inventory':[{'option_id':'95256891746','product_id':'16159309537','product_name':'비상 생존침낭','option_name':'1개 녹색','grade':'NEW','stock_available':0,'stock_inbound':100}],
        'api_inventory':[{'option_id':'95256891746','stock':0}],
        'product_prices':[
            {'option_id':'95256891746','product_id':'16159309537','product_name':'비상 생존침낭','option_name':'1개 녹색','sale_price':7900,'units_per_option':1},
            {'option_id':'95257064468','product_id':'16159309537','product_name':'비상 생존침낭','option_name':'2개 녹색','sale_price':14450,'units_per_option':2},
        ]
    }
    dec=answer(snapshot,'판매량 감소한 상품 뭐야?')
    assert '미확인' not in dec['answer']
    assert "묶음품절(모체 '1개 녹색' 단품재고 0개 공유)" in dec['answer']

