"""Small, explicitly dated summaries from Wing's customer-return analysis page."""
import re
from config import DATA
from src.finance import browser_snapshots, kst_timestamp


def latest_return_insight(data_dir=DATA):
    found=[]
    for path,payload in browser_snapshots(data_dir):
        for source in payload.get('sources',[]):
            if source.get('kind')!='customer_returns' or source.get('status')!='수집 완료':
                continue
            page=source.get('text','')
            rate=re.search(r'반품률\s*\((\d{1,2})월\)\s*([\d.]+)%',page)
            products=re.search(r'상품목록\s*\(총\s*([\d,]+)건\)',page)
            updated=re.search(r'최근 업데이트\s*(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.',page)
            if not rate or not updated:
                continue
            captured=kst_timestamp(source.get('captured_at',payload.get('received_at','')))
            found.append({'month':int(rate.group(1)),'rate':float(rate.group(2)),
                          'products':int(products.group(1).replace(',','')) if products else None,
                          'updated':f'{updated.group(1)}-{int(updated.group(2)):02d}-{int(updated.group(3)):02d}',
                          'captured_at':captured,'evidence':str(path)})
    return max(found,key=lambda row:row['captured_at']) if found else None
