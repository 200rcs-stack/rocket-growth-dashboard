"""Compare report scopes without treating different revenue measures as equal."""
from collections import defaultdict
from decimal import Decimal


def compare_revenue(inventory, api):
    excel = defaultdict(list)
    for row in inventory:
        excel[str(row['option_id'])].append(row)
    complete_api = isinstance(api.get('orders'), list) and bool(api.get('paid_from')) and bool(api.get('paid_to'))
    api_totals = defaultdict(Decimal)
    api_names = {}
    if complete_api:
        for order in api['orders']:
            for item in order['orderItems']:
                option = str(item['vendorItemId'])
                api_totals[option] += Decimal(str(item['unitSalesPrice'])) * Decimal(str(item['salesQuantity']))
                api_names[option] = item.get('productName', '')
    amounts = [r.get('rev_30d') for r in inventory]
    excel_total = sum(amounts) if amounts and all(v is not None for v in amounts) else None
    api_total = float(sum(api_totals.values())) if complete_api else None
    matched = float(sum(v for k, v in api_totals.items() if k in excel)) if complete_api else None
    unmatched = float(sum(v for k, v in api_totals.items() if k not in excel)) if complete_api else None
    rows = []
    for option in sorted(set(excel) | set(api_totals)):
        matches = excel.get(option, [])
        values = [r.get('rev_30d') for r in matches]
        report_amount = sum(values) if values and all(v is not None for v in values) else None
        order_amount = float(api_totals.get(option, Decimal(0))) if complete_api else None
        rows.append({'option_id': option,
                     'product_name': ' / '.join(dict.fromkeys(r.get('product_name', '') for r in matches)) if matches else api_names.get(option, ''),
                     'option_name': ' / '.join(dict.fromkeys(r.get('option_name') or '' for r in matches)),
                     'in_excel': bool(matches), 'in_api': option in api_totals,
                     'excel_amount': report_amount, 'api_amount': order_amount,
                     'difference': order_amount - report_amount if report_amount is not None and order_amount is not None else None})
    differing = [row for row in rows if row['difference'] not in (None, 0)]
    negative_total = sum(v for v in amounts if v is not None and v < 0)
    order_ids = [str(order['orderId']) for order in api.get('orders', []) if 'orderId' in order]
    return {'excel_amount': excel_total, 'excel_item_count': len(inventory), 'excel_option_count': len(excel),
            'excel_excludes_bundle': True, 'excel_period_label': '원본 표기 지난 30일 · 시작·종료일 미제공',
            'api_amount': api_total, 'api_start': api.get('paid_from'), 'api_end': api.get('paid_to'),
            'api_option_count': len(api_totals) if complete_api else None,
            'unmatched_option_count': sum(k not in excel for k in api_totals) if complete_api else None,
            'matched_api_amount': matched, 'unmatched_api_amount': unmatched,
            'difference': api_total - excel_total if api_total is not None and excel_total is not None else None,
            'remaining_difference': matched - excel_total if matched is not None and excel_total is not None else None,
            'same_scope_differences': differing,
            'negative_excel_amount': negative_total if excel_total is not None else None,
            'api_order_count': len(api['orders']) if complete_api else None,
            'api_quantity': sum(item['salesQuantity'] for order in api.get('orders', []) for item in order['orderItems']) if complete_api else None,
            'duplicate_order_count': len(order_ids) - len(set(order_ids)) if complete_api else None,
            'status': '범위 대조 완료 · 원인 대조 미완료' if complete_api and excel_total is not None else '비교 자료 미수집',
            'rows': rows}
