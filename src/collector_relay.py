"""Local IPC to the already paired Chrome collector; never exports its token."""
import json
import secrets
import threading
import time
from pathlib import Path
from config import DATA, DOWNLOADS
from src.aside_collector import collection_issues

PAIRING_PERSISTENCE = True


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def start_relay(bridge, data_dir=DATA):
    if bridge.port==8765 and data_dir==DATA:
        from src.credential_store import _windows_keyring
        _windows_keyring().set_password('Rocket Desk Chrome Collector','pairing',bridge.token)
    if getattr(bridge, '_web_relay', None):
        return
    def serve():
        handled = None
        while True:
            try:
                state = bridge.status()
                write_json(data_dir/'chrome_relay_health.json', {'time':time.time(), 'connected':state['connected']})
                request = data_dir/'chrome_relay_request.json'
                if request.exists():
                    job = json.loads(request.read_text(encoding='utf-8'))
                    if job.get('id') != handled and 0 <= time.time()-job.get('time',0) < 450:
                        handled = job['id']
                        if not state['connected']:
                            write_json(data_dir/'chrome_relay_result.json', {'id':handled,'error':'Chrome 수집기가 응답하지 않습니다.'})
                        else:
                            bridge.queue()
                            deadline = time.monotonic()+420
                            while time.monotonic()<deadline:
                                time.sleep(1)
                                state = bridge.status()
                                if state['status'] not in ('대기 중','수집 중'):
                                    break
                            write_json(data_dir/'chrome_relay_result.json', {'id':handled,'result':state})
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(1)
    bridge._web_relay = threading.Thread(target=serve, daemon=True)
    bridge._web_relay.start()


def available(data_dir=DATA):
    try:
        health=json.loads((data_dir/'chrome_relay_health.json').read_text(encoding='utf-8'))
        return health.get('connected',False) and 0 <= time.time()-health['time'] < 10
    except (OSError, ValueError, KeyError):
        return False


def collect(data_dir=DATA, timeout=450):
    if not available(data_dir):
        raise RuntimeError('연결된 Chrome 수집기가 없습니다.')
    job={'id':secrets.token_hex(16),'time':time.time()}
    write_json(data_dir/'chrome_relay_request.json',job)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            reply=json.loads((data_dir/'chrome_relay_result.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            reply={}
        if reply.get('id') == job['id']:
            result=reply.get('result',{})
            if reply.get('error') or not result.get('sources'):
                raise RuntimeError(reply.get('error') or result.get('status','Chrome 수집 실패'))
            for source in result['sources']:
                # Extension reports only completed basenames. Verify the exact
                # local file before declaring its download successful.
                source['downloads']=[{'status':'파일 저장 완료','name':f['name']}
                    for f in source.get('completed_files',[])
                    if f.get('state')=='complete' and isinstance(f.get('name'), str) and f['name']==Path(f['name']).name
                    and (DOWNLOADS/f['name']).is_file() and (DOWNLOADS/f['name']).stat().st_size>1000]
            issues=collection_issues(result['sources'])
            result['issues']=issues
            result['status']='일부 확인 필요' if issues else '수집 완료'
            # Preserve the validated download evidence for the web projection.
            payload={'id':job['id'],'received_at':result['received_at'],'sources':result['sources']}
            write_json(data_dir/('browser_snapshot_'+job['id']+'_chrome.json'),payload)
            write_json(data_dir/'browser_snapshot.json',payload)
            return result
        time.sleep(1)
    raise RuntimeError('Chrome 자료 수집 응답 시간이 초과됐습니다.')
