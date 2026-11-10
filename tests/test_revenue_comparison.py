from src.revenue_comparison import compare_revenue


def api(items):
    return {'paid_from':'2026-09-28','paid_to':'2026-10-27','orders':[{'orderItems':items}]}


def item(option,price,qty=1):
    return {'vendorItemId':option,'unitSalesPrice':str(price),'salesQuantity':qty,'productName':'상품'}


def test_comparison_splits_unmatched_options_without_claiming_the_remaining_cause():
    result=compare_revenue([{'option_id':'1','rev_30d':100,'product_name':'상품','option_name':'옵션'}],api([item(1,120),item(2,50,2)]))
    assert result['api_amount']==220
    assert result['matched_api_amount']==120 and result['unmatched_api_amount']==100
    assert result['difference']==120 and result['remaining_difference']==20
    assert result['unmatched_option_count']==1
    assert next(r for r in result['rows'] if r['option_id']=='2')['excel_amount'] is None
    assert '원인 대조 미완료' in result['status']


def test_same_option_multiple_grades_are_summed_once_and_negative_amounts_are_preserved():
    rows=[{'option_id':'1','rev_30d':100},{'option_id':'1','rev_30d':-25}]
    result=compare_revenue(rows,api([item(1,100)]))
    assert result['excel_amount']==75 and result['excel_option_count']==1
    assert len(result['rows'])==1 and result['remaining_difference']==25


def test_missing_report_values_and_missing_api_are_not_zero():
    assert compare_revenue([{'option_id':'1','rev_30d':None}],api([item(1,100)]))['difference'] is None
    result=compare_revenue([{'option_id':'1','rev_30d':100}],{})
    assert result['api_amount'] is None and result['rows'][0]['api_amount'] is None


def test_complete_empty_api_is_observed_zero_and_decimal_prices_are_stable():
    result=compare_revenue([{'option_id':'1','rev_30d':2.1}],api([item(1,'0.7',3)]))
    assert result['api_amount']==2.1 and result['difference']==0
    assert compare_revenue([{'option_id':'1','rev_30d':100}],api([]))['api_amount']==0


def test_same_scope_differences_keep_negative_report_entries_and_count_duplicates():
    source=api([item(1,120),item(3,50)])
    source['orders'][0]['orderId']=11
    source['orders'].append({'orderId':11,'orderItems':[]})
    result=compare_revenue([{'option_id':'1','rev_30d':100},{'option_id':'2','rev_30d':-25}],source)
    assert result['negative_excel_amount']==-25
    assert len(result['same_scope_differences'])==2
    assert sum(r['difference'] for r in result['same_scope_differences'])==result['remaining_difference']==45
    assert result['duplicate_order_count']==1
