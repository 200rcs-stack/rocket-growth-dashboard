"""Loopback-only bridge for the optional, user-installed read-only Wing collector."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock
from datetime import datetime
import json
import secrets
import time
from config import DATA, now

JOBS=[
 {'kind':'inventory','url':'https://wing.coupang.com/tenants/rfm-inventory/management/list'},
 {'kind':'settlement','url':'https://wing.coupang.com/tenants/rfm/settlements/home'},
 {'kind':'ad_billing','url':'https://wing.coupang.com/tenants/rfm-portal-2/cmg/settlement'},
 {'kind':'customer_returns','url':'https://wing.coupang.com/tenants/rfm/c-return/main'},
 {'kind':'ad_performance','url':'https://advertising.coupang.com/marketing/dashboard/sales'},
]

class Bridge:
    MAX_ACTIVE_SECONDS=390
    def __init__(self,port=8765,data_dir=DATA):
        self.port=port; self.data_dir=data_dir
        self.token=secrets.token_urlsafe(32)
        if port==8765 and data_dir==DATA:
            from src.credential_store import _windows_keyring
            vault=_windows_keyring()
            self.token=vault.get_password('Rocket Desk Chrome Collector','pairing') or self.token
            vault.set_password('Rocket Desk Chrome Collector','pairing',self.token)
        self.lock=Lock(); self.pending=None; self.active=None; self.last_seen=0; self.server=None
        self.last_period_seen=0
        self.last_rejected=0
        self.result={'status':'미연결','sources':[]}

    def queue(self,settlement_range=None):
        with self.lock:
            self.expire()
            if self.pending or self.active: return '기존 브라우저 수집 요청이 진행 중입니다.'
            selected=[{**next(j for j in JOBS if j['kind']=='settlement'),'range':settlement_range}] if settlement_range else JOBS
            self.pending={'id':secrets.token_hex(12),'jobs':selected,'created_at':now().isoformat()}
            self.result={'status':'대기 중','sources':[]}
        return '브라우저 수집 요청을 등록했습니다. 연결된 확장 프로그램이 최대 30초 내 시작합니다.'

    def status(self):
        with self.lock:
            self.expire()
            return {**self.result,'connected':time.time()-self.last_seen<90,'last_seen':self.last_seen,
                    'period_connected':time.time()-self.last_period_seen<90}

    def expire(self):
        if self.pending and time.time()-datetime.fromisoformat(self.pending['created_at']).timestamp()>60:
            self.pending=None; self.result={'status':'확장 프로그램 응답 없음 · 연결 상태 확인 필요','sources':[]}
        if self.active and time.time()-self.active['started']>self.MAX_ACTIVE_SECONDS:
            self.active=None; self.result={'status':'시간 초과 · 새로고침으로 다시 요청','sources':[]}

    def validate_sources(self,sources,jobs=JOBS):
        expected={j['kind']:j['url'] for j in jobs}
        if not isinstance(sources,list) or len(sources)!=len(expected): raise ValueError('Incomplete sources')
        seen=set()
        for source in sources:
            if not isinstance(source,dict): raise ValueError('Invalid source')
            kind=source.get('kind')
            if kind in seen or expected.get(kind)!=source.get('url'): raise ValueError('Invalid source')
            if not isinstance(source.get('status'),str) or not isinstance(source.get('text'),str): raise ValueError('Invalid content')
            if len(source['text'])>250000: raise ValueError('Oversized content')
            seen.add(kind)

    def start(self):
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def reply(self,status,payload):
                content=json.dumps(payload,ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(content)))
                self.end_headers(); self.wfile.write(content)
            def allowed(self):
                if self.headers.get('Host') not in [f'127.0.0.1:{bridge.port}',f'localhost:{bridge.port}']: return False
                return secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+bridge.token)
            def do_GET(self):
                if not self.allowed():
                    if self.path=='/job':bridge.last_rejected=time.time()
                    self.reply(403,{'error':'Unauthorized'}); return
                if self.path=='/health':
                    state=bridge.status()
                    self.reply(200,{key:state[key] for key in ('connected','period_connected','last_seen')}|
                               {'rejected_recently':time.time()-bridge.last_rejected<90})
                    return
                if self.path!='/job': self.reply(404,{}); return
                with bridge.lock:
                    bridge.last_seen=time.time()
                    if self.headers.get('X-Rocket-Settlement-Range')=='1':
                        bridge.last_period_seen=bridge.last_seen
                    bridge.expire()
                    job=bridge.pending
                    if job:
                        bridge.pending=None; bridge.active={'id':job['id'],'started':time.time(),'jobs':job['jobs']}
                        bridge.result={'status':'수집 중','sources':[]}
                self.reply(200,job or {})
            def do_POST(self):
                if not self.allowed(): self.reply(403,{'error':'Unauthorized'}); return
                if self.path!='/result': self.reply(404,{}); return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2_000_000: raise ValueError()
                    payload=json.loads(self.rfile.read(length))
                    with bridge.lock:
                        if not bridge.active or payload.get('id')!=bridge.active['id']:
                            self.reply(409,{'error':'Unknown job'}); return
                        sources=payload.get('sources',[])
                        jobs=bridge.active['jobs']
                        bridge.validate_sources(sources,jobs)
                        payload['received_at']=now().isoformat()
                        if not any(job.get('range') for job in jobs):
                            content=json.dumps(payload,ensure_ascii=False)
                            path=bridge.data_dir/('browser_snapshot_'+now().strftime('%Y%m%d%H%M%S')+'_'+payload['id']+'.json')
                            path.write_text(content,encoding='utf-8')
                            temp=bridge.data_dir/'browser_snapshot.tmp'
                            temp.write_text(content,encoding='utf-8'); temp.replace(bridge.data_dir/'browser_snapshot.json')
                        failed=any(s.get('status')!='수집 완료' for s in sources)
                        bridge.result={'status':'일부 확인 필요' if failed else '수집 완료','sources':sources,'received_at':payload['received_at']}
                        bridge.active=None
                    self.reply(200,{'ok':True})
                except (ValueError,KeyError,TypeError): self.reply(400,{'error':'Invalid result'})
        self.server=ThreadingHTTPServer(('127.0.0.1',self.port),Handler)
        self.port=self.server.server_address[1]
        Thread(target=self.server.serve_forever,daemon=True).start()
        return self
