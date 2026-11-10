"""Validated inventory-loss compensation and ad campaign exports from Wing."""
from pathlib import Path
import pandas as pd

from config import RAW
from src.parsers import identifier, rows


def parse_compensation(path):
    source = rows(path)
    required = {0: '발생일', 1: '정산주기(종료일)', 2: '주문ID',
                6: '옵션ID', 23: '검수번호', 28: '보상 금액'}
    if len(source) < 3 or len(source[1]) <= max(required) or any(source[1][column] != label for column, label in required.items()):
        raise ValueError('재고 손실 보상 파일의 열 구성이 다릅니다.')
    records = []
    for row in source[3:]:
        if not row[2]:
            continue  # Export footer, never a compensation transaction.
        order_no, option_id = identifier(row[2]), identifier(row[6])
        amount = pd.to_numeric(row[28], errors='coerce')
        period = pd.to_datetime(row[1], errors='coerce')
        if not order_no or not option_id or pd.isna(amount) or amount < 0 or pd.isna(period):
            raise ValueError('보상 상세의 주문·옵션·금액·정산주기를 확인할 수 없습니다.')
        records.append({'event_date': str(row[0]), 'period_end': period.date().isoformat(),
                        'order_no': order_no, 'option_id': option_id,
                        'product_name': str(row[7] or ''), 'option_name': str(row[8] or ''),
                        'event_type': str(row[3] or ''), 'damage_type': str(row[4] or ''),
                        'responsibility': str(row[24] or ''), 'inspection_no': identifier(row[23]),
                        'compensation_amount': int(amount), 'source_file': Path(path).name})
    result = pd.DataFrame.from_records(records)
    if not result.empty and result.duplicated(['period_end', 'order_no', 'option_id']).any():
        raise ValueError('같은 주문·옵션·정산주기가 중복됩니다.')
    return result


def load_compensation(raw_dir=RAW):
    candidates = sorted([*raw_dir.glob('inventory_compensation_*.xlsx'),
                         *raw_dir.glob('*-INVENTORY_COMPENSATION-*.xlsx')],
                        key=lambda p: p.stat().st_mtime, reverse=True)
    errors = []
    for path in candidates:
        try:
            parsed = parse_compensation(path)
            if not parsed.empty:
                return parsed, errors
        except ValueError as exc:
            errors.append(f'{path.name}: {exc}')
    return pd.DataFrame(), errors


def attach_compensation(returns, compensation):
    result = returns.copy()
    if result.empty:
        return result
    if compensation.empty:
        result['compensation_amount'] = float('nan')
        result['compensation_period'] = ''
        return result
    detail = compensation.rename(columns={'period_end': 'compensation_period'})[
        ['order_no', 'option_id', 'compensation_amount', 'compensation_period']]
    if detail.duplicated(['order_no', 'option_id']).any():
        raise ValueError('서로 다른 정산주기에 같은 주문·옵션 보상 기록이 있어 자동 대조할 수 없습니다.')
    return result.merge(detail, on=['order_no', 'option_id'], how='left', validate='m:1')


def parse_ad_campaigns(path):
    source = rows(path)
    if not source or list(source[0]) != ['번호', '광고유형', '캠페인 이름', '노출수', '클릭수', '광고비', '청구가능 광고비']:
        raise ValueError('광고 상세 파일의 열 구성이 다릅니다.')
    records = []
    for row in source[1:]:
        if not row[0]:
            continue
        spend, eligible = pd.to_numeric(row[5], errors='coerce'), pd.to_numeric(row[6], errors='coerce')
        if pd.isna(spend) or pd.isna(eligible) or spend < 0 or eligible < 0:
            raise ValueError('광고비 상세 금액을 확인할 수 없습니다.')
        records.append({'campaign': str(row[2]), 'ad_type': str(row[1]),
                        'impressions': pd.to_numeric(row[3], errors='coerce'),
                        'clicks': pd.to_numeric(row[4], errors='coerce'),
                        'spend': int(spend), 'eligible': int(eligible), 'source_file': Path(path).name})
    return pd.DataFrame.from_records(records)


def load_ad_campaigns(raw_dir=RAW):
    errors = []
    for path in sorted(raw_dir.glob('cmg_settlement_detail_*.xlsx'),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return parse_ad_campaigns(path), errors
        except ValueError as exc:
            errors.append(f'{path.name}: {exc}')
    return pd.DataFrame(), errors
