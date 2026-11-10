"""Summaries of verified Rocket Growth settlement-detail exports.

These exports cover a settlement cycle, not the dashboard's month-to-date
screen period. Keep their amounts separate until the scopes can be reconciled.
"""
from pathlib import Path
import pandas as pd

from config import RAW
from src.parsers import rows


REPORTS = {
    'CATEGORY_TR': ('판매수수료', None),
    'WAREHOUSING_SHIPPING': ('입출고·배송비', ('입출고비', '배송비')),
    'STORAGE_FEE': ('보관비', ('보관비',)),
    'CRETURN_PICKUP_RESTOCKING': ('반품 회수·재입고비', ('반품회수비', '반품재입고비')),
    'VRETURN_HANDLING': ('반출비', ('반출비',)),
    'VRETURN_SHIPPING': ('반출 배송 서비스비', ('반출 배송 서비스비 리포트',)),
    'VALUE_ADDED_SERVICE_FEE': ('부가서비스비', ('바코드 부가 서비스',)),
    'PPIR': ('리뷰 이벤트 비용', None),
}


def _amount(value, label):
    number = pd.to_numeric(value, errors='coerce')
    if pd.isna(number) or not float(number).is_integer():
        raise ValueError(f'{label} 금액을 읽을 수 없습니다.')
    return int(number)


def parse_settlement_export(path):
    name = Path(path).name
    matches = [code for code in REPORTS if f'-{code}-' in name]
    if len(matches) != 1:
        raise ValueError('지원하지 않는 정산 상세 파일명입니다.')
    code = matches[0]
    report, sheets = REPORTS[code]
    result = []
    if code == 'PPIR':
        source = rows(path, 0)
        if len(source) < 7 or source[5][0] != '정산유형' or source[5][14] != '리뷰 이벤트 수수료':
            raise ValueError('리뷰 이벤트 원본의 열 구성이 다릅니다.')
        if any(r[0] for r in source[7:]):
            raise ValueError('리뷰 이벤트 거래 행이 있어 별도 금액 매핑이 필요합니다.')
        return []  # Empty export has no period or amount; do not invent zero.
    if code == 'CATEGORY_TR':
        source = rows(path, 0)
        expected = {0: '정산유형', 1: '정산주기(종료일)', 4: '매출인식일',
                    5: '주문ID', 19: '매출금액(A*B-C)', 26: '판매수수료', 27: '판매수수료 VAT'}
        if len(source) < 3 or any(source[1][col] != label for col, label in expected.items()):
            raise ValueError('판매수수료 원본의 열 구성이 다릅니다.')
        transactions = [r for r in source[2:] if r[5]]
        if not transactions:
            raise ValueError('판매수수료 거래 행이 없습니다.')
        periods = {str(r[1]) for r in transactions}
        if len(periods) != 1:
            raise ValueError('한 파일에 서로 다른 정산주기가 있습니다.')
        result.append({'period_end': periods.pop(), 'report': report, 'part': '판매수수료',
                       'amount': sum(_amount(r[26], '판매수수료') + _amount(r[27], 'VAT') for r in transactions),
                       'sales': sum(_amount(r[19], '매출') for r in transactions),
                       'rows': len(transactions), 'source_file': name})
    else:
        for sheet in sheets:
            source = rows(path, sheet)
            if (len(source) < 4 or source[2][0] != '정산주기(종료일)'
                    or source[2][3] != '최종비용' or not str(source[2][1]).endswith('합계')):
                raise ValueError(f'{sheet} 원본의 합계 열 구성이 다릅니다.')
            period = str(source[3][0])
            amount = _amount(source[3][3], sheet)
            if _amount(source[3][1], sheet) + _amount(source[3][2], '세액') != amount:
                raise ValueError(f'{sheet} 세전 금액·세액·최종비용이 일치하지 않습니다.')
            result.append({'period_end': period, 'report': report, 'part': sheet,
                           'amount': amount, 'sales': None, 'rows': None,
                           'source_file': name})
    if any(pd.isna(pd.to_datetime(r['period_end'], errors='coerce')) for r in result):
        raise ValueError('정산주기 날짜를 확인할 수 없습니다.')
    return result


_SETTLEMENT_CACHE = {}

def load_settlement_exports(raw_dir=RAW):
    found, errors, seen = [], [], set()
    candidates = sorted((p for p in raw_dir.glob('*.xlsx') if any(f'-{code}-' in p.name for code in REPORTS)),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            st = path.stat()
            ckey = (str(path.resolve()), st.st_mtime_ns, st.st_size)
            if ckey not in _SETTLEMENT_CACHE:
                _SETTLEMENT_CACHE[ckey] = parse_settlement_export(path)
            entries = _SETTLEMENT_CACHE[ckey]
            for entry in entries:
                key = (entry['period_end'], entry['part'])
                if key not in seen:
                    found.append(dict(entry))
                    seen.add(key)
        except (ValueError, IndexError, KeyError) as exc:
            errors.append(f'{path.name}: {exc}')
    return sorted(found, key=lambda r: (r['period_end'], r['part']), reverse=True), errors
