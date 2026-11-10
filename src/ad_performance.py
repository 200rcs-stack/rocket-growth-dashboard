"""Validate the official Coupang Ads daily product report before showing it."""
from pathlib import Path
import re
import pandas as pd
from config import RAW

FILENAME = re.compile(r'A[0-9A-Za-z]+_pa_daily_vendorItem_(20\d{6})_(20\d{6})(?:_[a-f0-9]{64})?\.xlsx$')
COLUMNS = {
    '날짜': 'date', '캠페인 ID': 'campaign_id', '캠페인명': 'campaign',
    '광고집행 상품명': 'product', '광고집행 옵션ID': 'option_id',
    '광고전환매출발생 옵션ID': 'conversion_option_id', '광고 노출 지면': 'placement',
    '노출수': 'impressions', '클릭수': 'clicks', '광고비': 'spend',
    '총 주문수(1일)': 'orders_1d', '총 전환매출액(1일)': 'sales_1d',
    '총 주문수(14일)': 'orders_14d', '총 전환매출액(14일)': 'sales_14d',
}
COUNTS = ('impressions', 'clicks', 'spend', 'orders_1d', 'sales_1d', 'orders_14d', 'sales_14d')


def parse_ad_performance(path):
    match = FILENAME.fullmatch(Path(path).name)
    if not match:
        raise ValueError('광고 성과 보고서 파일명이 예상 형식과 다릅니다.')
    raw = pd.read_excel(path)
    if raw.empty or raw.columns.duplicated().any() or not set(COLUMNS).issubset(raw.columns):
        raise ValueError('광고 성과 보고서의 필수 열이 없거나 중복됐습니다.')
    if len(raw.columns) != 44:
        raise ValueError('광고 성과 보고서 열 구성이 변경됐습니다.')
    report = raw.rename(columns=COLUMNS)[list(COLUMNS.values())].copy()
    dates = pd.to_numeric(report.date, errors='coerce')
    if dates.isna().any() or not dates.mod(1).eq(0).all():
        raise ValueError('광고 성과 보고서 날짜를 확인할 수 없습니다.')
    report['date'] = pd.to_datetime(dates.astype('int64').astype(str), format='%Y%m%d', errors='coerce')
    start, end = (pd.to_datetime(value, format='%Y%m%d') for value in match.groups())
    if report.date.isna().any() or start > end or not report.date.between(start, end).all():
        raise ValueError('광고 성과 보고서의 기간과 행 날짜가 맞지 않습니다.')
    for column in ('campaign_id', 'option_id'):
        values = pd.to_numeric(report[column], errors='coerce')
        if values.isna().any() or not values.mod(1).eq(0).all() or (values <= 0).any():
            raise ValueError('광고 성과 보고서의 캠페인·옵션 ID를 확인할 수 없습니다.')
        report[column] = values.astype('int64').astype(str)
    conversion_ids = pd.to_numeric(report.conversion_option_id, errors='coerce')
    if conversion_ids.dropna().mod(1).ne(0).any():
        raise ValueError('광고 전환 옵션 ID 형식이 잘못됐습니다.')
    report['conversion_option_id'] = conversion_ids.astype('Int64').astype(str).replace('<NA>', '')
    for column in COUNTS:
        values = pd.to_numeric(report[column], errors='coerce')
        if values.isna().any() or (values < 0).any() or not values.mod(1).eq(0).all():
            raise ValueError('광고 성과 보고서 수치가 비어 있거나 잘못됐습니다.')
        report[column] = values.astype('int64')
    report['source_file'] = Path(path).name
    return report


_AD_PERF_CACHE = {}

def load_ad_performance(raw_dir=RAW):
    errors = []
    for path in sorted(raw_dir.glob('A*_pa_daily_vendorItem_*.xlsx'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            st = path.stat()
            key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
            if key not in _AD_PERF_CACHE:
                _AD_PERF_CACHE[key] = parse_ad_performance(path)
            return _AD_PERF_CACHE[key].copy(), path, errors
        except Exception as exc:
            errors.append(f'{path.name}: {exc}')
    return pd.DataFrame(), None, errors
