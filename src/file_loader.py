import hashlib
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path
import pandas as pd
from config import RAW, DATA, DOWNLOADS, now
from src.parsers import identifier, rows, parse_inventory, parse_returns, parse_reconciliation, inspect_workbook
from src.compensation import parse_compensation, parse_ad_campaigns
from src.ad_performance import parse_ad_performance, FILENAME as AD_PERFORMANCE_FILENAME
from src.settlement_exports import REPORTS, parse_settlement_export, load_settlement_exports

PATTERNS={'inventory':'inventory_health_sku_info_', 'returns':'inventory_health_creturn_v2_info_',
          'reconciliation':'inventory_reconciliation_report_'}

def recognized_download(name):
    return (any(name.startswith(prefix) for prefix in PATTERNS.values())
            or name.startswith('cmg_settlement_detail_')
            or bool(AD_PERFORMANCE_FILENAME.fullmatch(name))
            or bool(re.fullmatch(r'[A-Z]\d+-INVENTORY_COMPENSATION-.*\.xlsx', name))
            or any(f'-{code}-' in name for code in REPORTS))

_HASH_CACHE = {}
_PARSE_CACHE = {}
_RECORDED_CACHE = set()

def digest(path):
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return _HASH_CACHE[key]

def _cached_parse(kind, path, fn, extra_key=None):
    file_hash = digest(path)
    key = (kind, file_hash, extra_key)
    if key not in _PARSE_CACHE:
        _PARSE_CACHE[key] = fn(path)
    val = _PARSE_CACHE[key]
    if isinstance(val, pd.DataFrame):
        copied = val.copy()
        copied.attrs = dict(val.attrs)
        return copied
    return val

def sync_downloads():
    copied=[]
    known_hashes={digest(path) for path in RAW.glob('*.xlsx')}
    for path in DOWNLOADS.glob('*.xlsx'):
        if not recognized_download(path.name): continue
        if time.time()-path.stat().st_mtime<2: continue
        file_hash=digest(path)
        if file_hash in known_hashes: continue
        dest=RAW/path.name
        # Report names can be reused by Wing. Preserve both versions rather than
        # silently dropping changed data or replacing a previously verified file.
        if dest.exists():
            dest=RAW/(path.stem+'_'+file_hash+path.suffix)
        if not dest.exists():
            temp=dest.with_suffix('.tmp')
            shutil.copy2(path,temp)
            temp.replace(dest)
            copied.append(dest.name)
            known_hashes.add(file_hash)
    return copied

def timestamp(path):
    match=re.search(r'(20\d{12})',path.name)
    if match:
        try: return pd.to_datetime(match.group(1),format='%Y%m%d%H%M%S').isoformat()
        except ValueError: pass
    return pd.Timestamp(path.stat().st_mtime,unit='s',tz='UTC').tz_convert('Asia/Seoul').isoformat()

def record_file(path,kind,status,count,message=''):
    file_hash=digest(path)
    db_path=DATA/'rocket_growth.db'
    cache_key=(str(db_path.resolve()),file_hash,kind,status,count,message)
    if cache_key in _RECORDED_CACHE and db_path.exists(): return
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS files (sha256 TEXT PRIMARY KEY, name TEXT, kind TEXT, source_time TEXT, imported_at TEXT, rows INTEGER, status TEXT, message TEXT)')
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET rows=excluded.rows,status=excluded.status,message=excluded.message',
           (file_hash,path.name,kind,timestamp(path),now().isoformat(),count,status,message))
    _RECORDED_CACHE.add(cache_key)

def _extract_storage_names(path):
    names = {}
    try:
        for row in rows(path, '보관비')[8:]:
            if len(row) > 11 and row[8]:
                oid = identifier(row[8])
                pname = str(row[10] or '').strip()
                oname = str(row[11] or '').strip()
                if oid and pname:
                    names.setdefault(oid, {'product_name': pname, 'option_name': oname, 'product_id': identifier(row[7]) or None, 'origin': '정산 상세 보관비 원본'})
    except Exception:
        pass
    return names

def load_data():
    sync_downloads()
    result={'inventory':pd.DataFrame(),'returns':pd.DataFrame(),'reconciliation':pd.DataFrame(), 'files':[], 'errors':[], 'option_names':{}}
    today=now().date()
    for kind,prefix in PATTERNS.items():
        candidates=sorted(RAW.glob(prefix+'*.xlsx'),key=lambda p:(timestamp(p),p.stat().st_mtime_ns),reverse=True)
        selected=False
        fn=parse_inventory if kind=='inventory' else (lambda p:parse_returns(p,today)) if kind=='returns' else parse_reconciliation
        extra=(id(parse_inventory) if kind=='inventory' else (id(parse_returns),today) if kind=='returns' else id(parse_reconciliation))
        for path in candidates:
            info={'name':path.name,'kind':kind,'time':timestamp(path),'bytes':path.stat().st_size,'active':False}
            try:
                df=_cached_parse(('primary',kind),path,fn,extra)
                info.update(rows=len(df),status='검증 완료')
                if not selected:
                    result[kind]=df
                    info['active']=True
                    selected=True
                    result[kind+'_time']=timestamp(path)
                if kind=='inventory' and {'option_id','product_name','option_name'}.issubset(df.columns):
                    for _,r in df.iterrows():
                        oid=str(r.option_id)
                        if oid and r.product_name:
                            result['option_names'].setdefault(oid,{'product_name':str(r.product_name),'option_name':str(r.option_name or ''),'grade':str(r.get('grade') or '') or None,'product_id':str(r.get('product_id') or '') or None,'origin':'이전 Wing 재고 원본'})
                elif kind=='reconciliation' and {'option_id','product_name'}.issubset(df.columns):
                    for _,r in df.iterrows():
                        oid=str(r.option_id)
                        raw_name=str(r.product_name or '').strip()
                        if oid and raw_name and oid not in result['option_names']:
                            parts=[x.strip() for x in raw_name.rsplit(',',1)]
                            result['option_names'][oid]={'product_name':parts[0],'option_name':parts[1] if len(parts)>1 else '','product_id':str(r.get('product_id') or '') or None,'origin':'이전 재고변동 원본'}
                record_file(path,kind,'ok',len(df))
            except Exception as ex:
                info.update(rows=None,status='읽기 실패',error=str(ex))
                result['errors'].append(path.name+': '+str(ex))
                record_file(path,kind,'error',0,str(ex))
            result['files'].append(info)
    # Financial reports are mapped only after their exported headers are verified.
    selected_extra=set()
    selected_settlement_files={entry['source_file'] for entry in load_settlement_exports(RAW)[0]}
    for path in sorted(RAW.glob('*.xlsx'),key=lambda p:(timestamp(p),p.stat().st_mtime_ns),reverse=True):
        if any(path.name.startswith(p) for p in PATTERNS.values()): continue
        try:
            if path.name.startswith('inventory_compensation_') or '-INVENTORY_COMPENSATION-' in path.name:
                kind='compensation'; count=_cached_parse(('count',kind),path,lambda p:len(parse_compensation(p)))
            elif path.name.startswith('cmg_settlement_detail_'):
                kind='ad_campaigns'; count=_cached_parse(('count',kind),path,lambda p:len(parse_ad_campaigns(p)))
            elif AD_PERFORMANCE_FILENAME.fullmatch(path.name):
                kind='ad_performance'; count=_cached_parse(('count',kind),path,lambda p:len(parse_ad_performance(p)))
            elif any(f'-{code}-' in path.name for code in REPORTS):
                kind='settlement_detail'; count=_cached_parse(('count',kind),path,lambda p:len(parse_settlement_export(p)))
                if '-STORAGE_FEE-' in path.name:
                    for oid,meta in _cached_parse(('storage_names',kind),path,_extract_storage_names).items():
                        result['option_names'].setdefault(oid,meta)
            else:
                kind='other'; count=_cached_parse(('count',kind),path,lambda p:sum(s['rows'] for s in inspect_workbook(p)))
            active=(path.name in selected_settlement_files if kind=='settlement_detail'
                    else kind!='other' and kind not in selected_extra and not (kind=='compensation' and count==0))
            if active and kind!='settlement_detail': selected_extra.add(kind)
            result['files'].append({'name':path.name,'kind':kind,'time':timestamp(path),'bytes':path.stat().st_size,
                                    'active':active,'rows':count,'status':('거래 없는 빈 원본' if kind in ('settlement_detail','compensation') and count==0
                                                                          else '검증 완료' if kind!='other' else '원본 보관 · 매핑 필요')})
            record_file(path,kind,'ok' if kind!='other' else 'unmapped',count)
        except Exception as ex:
            result['errors'].append(path.name+': '+str(ex))
            record_file(path,'other','error',0,str(ex))
    result['scan_time']=now().isoformat()
    return result

def save_upload(name,content):
    name=Path(name).name
    if not name.endswith('.xlsx') or len(content)>50*1024*1024: raise ValueError('50MB 이하 .xlsx 파일만 가능합니다.')
    path=RAW/name
    if path.exists() and path.read_bytes()!=content:
        path=RAW/(path.stem+'_'+hashlib.sha256(content).hexdigest()+path.suffix)
    temp=path.with_suffix('.tmp')
    temp.write_bytes(content)
    inspect_workbook(temp)
    temp.replace(path)
    return path
