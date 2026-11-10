"""Parse observed Wing exports; reject unknown schemas rather than shift columns silently."""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd
import openpyxl
from io import BytesIO

INVENTORY_COLUMNS = ['no','product_id','option_id','sku_id','product_name','option_name','grade',
 'stock_available','stock_inbound','item_winner','rev_7d','rev_30d','qty_7d','qty_30d',
 'doc_days','forecast_1w','forecast_5w','forecast_10w','restock_rec_qty','restock_rec_date',
 'doc_label','storage_fee_mtd','age_1_30','age_31_45','age_46_60','age_61_120','age_121_180',
 'age_181_plus','returns_30d','season_mgmt','reg_date']
NUMBERS = ['stock_available','stock_inbound','rev_7d','rev_30d','qty_7d','qty_30d',
 'doc_days','forecast_1w','forecast_5w','forecast_10w','restock_rec_qty','storage_fee_mtd',
 'age_1_30','age_31_45','age_46_60','age_61_120','age_121_180','age_181_plus','returns_30d']

# Both header rows matter: a changed rolling period must never be read as the
# old period simply because the option ID and stock columns still match.
INVENTORY_HEADER = ['No.','등록상품 ID','옵션 ID','SKU ID','등록상품명','옵션명','상품등급',
 '판매가능재고 (실시간 기준)','입고예정재고(실시간 기준)','아이템위너','최근 매출 (번들 매출 제외)',None,
 '최근 판매수량',None,'예상 소진일 (DOC)','판매 예측 (1주)','판매 예측 (5주)','판매 예측 (10주)',
 '추가입고\n추천수량','추가입고날짜 (입고예정일)','재고예상\n소진일','이번달 누적보관료(전일자 기준)',
 '보관기간별 판매가능재고 (전일자 기준)',None,None,None,None,None,'고객반품 지난 30일(전일자 기준)','시즌관리','상품등록일']
INVENTORY_SUBHEADER = [None]*10+['지난 7일','지난 30일','지난 7일','지난 30일']+[None]*8+[
 '1~30일','31~45일','46~60일','61~120일','121~180일','181일+']+[None]*3


def valid_inventory_header(raw):
    if len(raw)<2 or len(raw[0])!=31 or len(raw[1])!=31: return False
    header=list(raw[0])
    # Two observed, equivalent labels in the preserved original exports.
    if header[14]=='현재 DOC (일)': header[14]='예상 소진일 (DOC)'
    return header==INVENTORY_HEADER and list(raw[1])==INVENTORY_SUBHEADER

def identifier(value):
    if value is None or pd.isna(value): return ''
    s = str(value).strip()
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    if re.fullmatch(r'\d+(?:\.0+)?', s): return s.split('.')[0]
    if re.fullmatch(r'\d+(?:\.\d+)?[eE][+]?[0-9]+', s):
        try:
            n=Decimal(s)
            return str(int(n)) if n == n.to_integral_value() else ''
        except InvalidOperation: return ''
    return ''

def num(series):
    return pd.to_numeric(series.astype('string').str.replace(',','',regex=False).str.replace('원','',regex=False).str.strip(), errors='coerce').astype(float)

def rows(path, sheet=0):
    wb=openpyxl.load_workbook(BytesIO(Path(path).read_bytes()),read_only=True,data_only=True)
    try:
        ws=wb.worksheets[sheet] if isinstance(sheet,int) else wb[sheet]
        return list(ws.values)
    finally: wb.close()

def parse_inventory(path):
    raw=rows(path)
    if not valid_inventory_header(raw):
        raise ValueError('재고 파일 헤더가 검증된 31열 형식과 다릅니다. 원본 확인이 필요합니다.')
    df=pd.DataFrame(raw[2:],columns=INVENTORY_COLUMNS)
    for col in ['product_id','option_id','sku_id']: df[col]=df[col].map(identifier)
    if df.option_id.eq('').any(): raise ValueError('재고 파일에 해석할 수 없는 옵션 ID가 있습니다.')
    if df.duplicated(['option_id','sku_id','grade']).any(): raise ValueError('재고 파일에 같은 옵션·SKU·등급이 중복되어 있습니다.')
    for col in NUMBERS: df[col]=num(df[col])
    df['source_file']=Path(path).name
    return df

RETURN_ALIASES={'접수일자':'request_date','접수일':'request_date','반품접수일':'request_date',
 '유형':'return_type','반품유형':'return_type','반품번호':'return_no','주문번호':'order_no',
 '옵션 ID':'option_id_raw','옵션ID':'option_id_raw','등록상품명,옵션명':'product_name',
 '등록상품명，옵션명':'product_name','등록상품명':'product_name','상품명':'product_name',
 '고객 반품 사유':'reason','반품사유':'reason','검수번호':'inspection_no','검수 등급':'return_grade',
 '검수등급':'return_grade','처리상태':'process_status','반품수량':'return_qty','반품 수량':'return_qty'}

def parse_returns(path, reference_date):
    raw=rows(path)
    if len(raw)<7: raise ValueError('반품 파일의 헤더/설명 행을 확인할 수 없습니다.')
    headers=[str(v).strip() if v is not None else f'blank_{i}' for i,v in enumerate(raw[5])]
    df=pd.DataFrame(raw[7:],columns=headers).rename(columns=RETURN_ALIASES)
    required={'request_date','return_no','option_id_raw','process_status'}
    if not required.issubset(df.columns): raise ValueError('반품 필수 열이 없습니다: '+', '.join(required-set(df.columns)))
    df=df.dropna(subset=['return_no']).copy()
    df['option_id']=df.option_id_raw.map(identifier)
    df['return_no']=df.return_no.map(identifier)
    if df.option_id.eq('').any() or df.return_no.eq('').any(): raise ValueError('반품 파일의 ID를 확인해 주세요.')
    df['grade_suffix']=df.option_id_raw.astype(str).str.extract(r'\(([^)]+)\)',expand=False)
    df['request_date']=pd.to_datetime(df.request_date,errors='coerce')
    if df.request_date.isna().any(): raise ValueError('반품 접수일자 형식을 확인해 주세요.')
    df['elapsed_days']=(pd.Timestamp(reference_date).normalize()-df.request_date).dt.days
    df['overdue']=df.process_status.eq('회수중') & df.elapsed_days.ge(90)
    df['disposed']=df.process_status.eq('폐기')
    # Current actual export contains cases, not quantities. Never invent quantity=1.
    df['return_qty']=num(df['return_qty']) if 'return_qty' in df else float('nan')
    df['source_file']=Path(path).name
    for col in ['order_no','product_name','reason','inspection_no','return_grade']:
        if col not in df: df[col]=''
    return df.drop(columns=[c for c in df if c.startswith('blank_')])

def parse_reconciliation(path):
    raw=rows(path,0)
    if len(raw)<17 or raw[13][2]!='옵션 ID': raise ValueError('재고변동 파일의 3단 헤더를 확인해 주세요.')
    if raw[15][8]=='입고 (C)':
        cols=['blank','product_id','option_id','sku_id','product_name','before','transferred','inbound_requested',
              'inbound','outbound','reshipped','returned','removed','adjusting','lost','emergency_lost','after']
    elif raw[15][8]=='입고 (C1)' and str(raw[15][17]).startswith('변경 후'):
        cols=['blank','product_id','option_id','sku_id','product_name','before','transferred','inbound_requested',
              'inbound','allocating','delayed','outbound','reshipped','returned','removed','adjusting','lost','after']
    else: raise ValueError('지원하지 않는 재고변동 열 구조입니다.')
    df=pd.DataFrame([list(r[:len(cols)]) for r in raw[17:] if any(v is not None for v in r)],columns=cols)
    for c in ['product_id','option_id','sku_id']: df[c]=df[c].map(identifier)
    for c in cols[5:]: df[c]=num(df[c])
    # The downloaded report explicitly states all movements are SIGNED and added.
    movement=[c for c in cols[5:] if c not in ['inbound_requested','after']]
    df['calculated_after']=df[movement].sum(axis=1,min_count=len(movement))
    df['difference']=df.after-df.calculated_after
    df['loss_review']=df.lost.abs().gt(0) | (df.emergency_lost.abs().gt(0) if 'emergency_lost' in df else False)
    df['source_file']=Path(path).name
    df.attrs['period']=str(raw[0][1])
    return df.drop(columns=['blank'])

def inspect_workbook(path):
    wb=openpyxl.load_workbook(BytesIO(Path(path).read_bytes()),read_only=True,data_only=True)
    try:
        return [{'sheet':s.title,'rows':s.max_row,'columns':s.max_column} for s in wb]
    finally: wb.close()
