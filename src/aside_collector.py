"""Collect visible Coupang pages through the user's installed Aside browser."""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from config import DATA, DOWNLOADS, ROOT, now
from src.browser_bridge import JOBS


SCRIPT = ROOT / 'src' / 'aside_collect.js'
ASIDE_BROWSER = Path('C:/Program Files/Aside/Application/Aside.exe')

REQUIRED_DOWNLOADS = {
    'inventory': ('inventory_health_sku_info_', 'inventory_health_creturn_v2_info_'),
    'ad_billing': ('cmg_settlement_detail_',),
}

class AsideCollectionError(RuntimeError):
    """A safe, user-facing browser collection failure."""


def failure_status(output):
    if re.search(r'RefStaleError|is stale', output, re.I):
        return '화면이 바뀌어 클릭 대상 확인 실패'
    if re.search(r'Cookie not found', output, re.I):
        return '쿠팡윙 로그인 필요'
    if re.search(r"Aside isn't running|connection refused|cannot connect", output, re.I):
        return 'Aside 브라우저 연결 필요'
    return 'Aside 수집 실행 실패'


def read_collector_result(stdout, stderr='', returncode=0):
    # The REPL's pwd is a session workspace, not necessarily a path visible
    # to the Windows collector. Consume its JSON directly without logging it.
    output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', stdout)
    match = re.search(r'^ASIDE_RESULT_JSON=(.+)$', output, re.M)
    if returncode or not match:
        raise AsideCollectionError(failure_status(stdout + stderr))
    try:
        result = json.loads(match.group(1))
    except ValueError:
        raise AsideCollectionError('Aside 수집 결과를 읽지 못함') from None
    if not isinstance(result, dict):
        raise AsideCollectionError('Aside 수집 결과 형식 확인 필요')
    return result


def collection_issues(sources):
    """A rendered page alone is not proof that its required files were saved."""
    labels = {'inventory':'재고·반품 엑셀', 'settlement':'정산 화면',
              'customer_returns':'반품 분석 화면', 'ad_billing':'광고비', 'ad_performance':'광고센터'}
    issues = []
    for item in sources:
        label = labels.get(item['kind'], item['kind'])
        if item['status'] != '수집 완료':
            issues.append(label + ': ' + item['status'])
            continue
        saved = [d.get('name', '') for d in item.get('downloads', []) if d.get('status') == '파일 저장 완료']
        for prefix in REQUIRED_DOWNLOADS.get(item['kind'], ()):
            if not any(name.startswith(prefix) for name in saved):
                issues.append(label + ': 원본 다운로드 미완료 (' + prefix.rstrip('_') + ')')
    return issues


def collect(data_dir=DATA, timeout=180, kinds=None, settlement_range=None):
    if kinds is None:
        # Each source gets its own REPL timeout. A slow Wing screen cannot
        # discard already verified files from other sources.
        sources=[]
        wing_logged_out=False
        for job in JOBS:
            if wing_logged_out and job['kind'] in ('settlement','ad_billing','customer_returns'):
                sources.append({**job,'captured_at':now().isoformat(),'status':'쿠팡윙 로그인 필요','text':'','note':'기존 성공 원본 유지'})
                continue
            try:
                result=collect(data_dir=data_dir, timeout=timeout, kinds=[job['kind']])
                sources.extend(result['sources'])
                if job['kind']=='inventory' and any(s.get('status')=='쿠팡윙 로그인 필요' for s in result['sources']):
                    wing_logged_out=True
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                status = (str(error) if isinstance(error, AsideCollectionError) else
                          'Aside 화면 응답 시간 초과' if isinstance(error, subprocess.TimeoutExpired) else
                          'Aside 수집 실행 실패')
                if status=='쿠팡윙 로그인 필요':
                    wing_logged_out=True
                sources.append({**job,'captured_at':now().isoformat(),
                                'status':status,'text':'',
                                'note':'기존 성공 원본 유지'})
        payload={'id':'aside-'+now().strftime('%Y%m%d%H%M%S'),
                 'received_at':now().isoformat(),'sources':sources}
        content=json.dumps(payload,ensure_ascii=False)
        (data_dir/('browser_snapshot_'+payload['id']+'.json')).write_text(content,encoding='utf-8')
        temporary=data_dir/'browser_snapshot.tmp'
        temporary.write_text(content,encoding='utf-8')
        temporary.replace(data_dir/'browser_snapshot.json')
        issues=collection_issues(sources)
        return {'status':'일부 확인 필요' if issues else '수집 완료','issues':issues,
                'sources':sources,'received_at':payload['received_at']}
    executable = shutil.which('aside')
    if not executable:
        raise AsideCollectionError('Aside CLI를 찾을 수 없음')
    expected = {job['kind']: job['url'] for job in JOBS}
    selected = list(expected) if kinds is None else list(kinds)
    if not selected or len(set(selected)) != len(selected) or any(kind not in expected for kind in selected):
        raise ValueError('지원하지 않는 수집 대상입니다.')
    expected = {kind:expected[kind] for kind in selected}
    script = ('const selectedKinds = '+json.dumps(selected)+';\n'
              +'const settlementRange = '+json.dumps(settlement_range)+';\n'
              +SCRIPT.read_text(encoding='utf-8'))
    def invoke():
        return subprocess.run(
            [executable, 'repl', script], cwd=ROOT, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=min(timeout,110),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False,
        )

    completed = invoke()
    failure = completed.stdout + completed.stderr
    if (not re.search(r'^ASIDE_RESULT_JSON=', completed.stdout, re.M) and ASIDE_BROWSER.is_file()
            and 'Aside isn\'t running' in failure):
        if 'Aside isn\'t running' in failure:
            subprocess.Popen([str(ASIDE_BROWSER)], cwd=ASIDE_BROWSER.parent,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        completed = invoke()
    payload = read_collector_result(completed.stdout, completed.stderr, completed.returncode)
    sources = payload.get('sources')
    if not isinstance(sources, list) or len(sources) != len(expected):
        raise RuntimeError('Aside 화면별 결과가 누락되었습니다.')
    seen = set()
    for item in sources:
        kind = item.get('kind')
        if kind in seen or expected.get(kind) != item.get('url') or item.get('status') not in (
            '수집 완료', '화면 본문 확인 필요', '쿠팡윙 본문 로딩 실패', '쿠팡윙 로그인 필요',
            '광고센터 로그인 필요', '광고센터 이번달 화면 확인 필요', 'Wing 조회기간 선택 확인 필요'
        ) or not isinstance(item.get('text'), str) or len(item['text']) > 250000:
            raise RuntimeError('Aside 화면 결과 형식이 올바르지 않습니다.')
        allowed = {'inventory': ('inventory_health_sku_info_', 'inventory_health_creturn_v2_info_'),
                   'ad_billing': ('cmg_settlement_detail_',)}.get(kind, ())
        downloads = item.get('downloads', [])
        if not isinstance(downloads, list) or len(downloads) > len(allowed):
            raise RuntimeError('Aside 다운로드 결과 형식이 올바르지 않습니다.')
        for download in downloads:
            if download.get('status') != '파일 저장 완료':
                continue
            filename = download.get('name', '')
            file = Path(download.get('file', '')).resolve()
            if (not any(filename.startswith(prefix) for prefix in allowed)
                    or file.parent != DOWNLOADS.resolve() or file.name != filename
                    or file.suffix.lower() != '.xlsx' or not file.is_file()
                    or file.stat().st_size != download.get('size') or file.stat().st_size < 1000):
                raise RuntimeError('Aside 다운로드 파일 검증에 실패했습니다.')
        seen.add(kind)
    content = json.dumps(payload, ensure_ascii=False)
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = data_dir / ('browser_snapshot_' + now().strftime('%Y%m%d%H%M%S') + '_aside.json')
    if settlement_range is None:
        archive.write_text(content, encoding='utf-8')
    issues = collection_issues(sources)
    return {'status': '수집 완료' if not issues else '일부 확인 필요', 'issues': issues,
            'sources': sources, 'received_at': payload['received_at']}
