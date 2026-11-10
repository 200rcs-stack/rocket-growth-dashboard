"""Single-PC collector for the owner-private Site. All secrets remain local."""
import argparse
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from urllib.parse import urlparse
import requests
from config import ROOT, DATA, RAW, now
from src.credential_store import _windows_keyring, load_credentials
from src.coupang_api import CoupangReader
from src.web_snapshot import build_snapshot
from src.ai_advisor import advice

SERVICE='Rocket Desk Private Web'
ALLOWED_HOST='rocket-desk-watnimall.mindery1.chatgpt.site'


class Sync:
    def __init__(self, local=None):
        if local:
            if local!='http://127.0.0.1:3100': raise ValueError('Unknown preview origin')
            self.origin=local; self.headers={}
        else:
            raw=_windows_keyring().get_password(SERVICE,'active')
            if not raw: raise RuntimeError('웹 연결 자격 증명이 없습니다.')
            config=json.loads(raw)
            if config['origin']!='https://'+ALLOWED_HOST: raise RuntimeError('허용되지 않은 동기화 대상')
            self.origin=config['origin'];self.headers={'OAI-Sites-Authorization':'Bearer '+config['token']}
        self.cache=DATA/('web_uploaded_preview.json' if local else 'web_uploaded.json')
        self.uploaded=set(json.loads(self.cache.read_text()) if self.cache.exists() else [])
        self.period_bridge=None
        self._tls=threading.local()

    def start_period_bridge(self):
        from src.browser_bridge import Bridge
        try:
            if _windows_keyring().get_password('Rocket Desk Chrome Collector','pairing'):
                self.period_bridge=Bridge().start()
        except (OSError,RuntimeError):
            pass

    def chrome_period(self,range_):
        bridge=getattr(self,'period_bridge',None)
        # Some Chrome profiles connect without the capability header. Ask the
        # paired collector and reject the result unless Wing's period matches.
        if not bridge or not bridge.status()['connected']:return None
        bridge.queue(settlement_range=range_)
        requeued=False
        deadline=time.monotonic()+135
        while time.monotonic()<deadline:
            state=bridge.status()
            if state['status'] not in ('대기 중','수집 중'):
                if state.get('sources'):
                    return state
                if not requeued and state['status'].startswith('확장 프로그램 응답 없음') and time.monotonic()+30<deadline:
                    bridge.queue(settlement_range=range_)
                    requeued=True
                    continue
                return None
            time.sleep(1)
        return None

    def chrome_full(self):
        bridge=getattr(self,'period_bridge',None)
        if not bridge or not bridge.status()['connected']:return None
        bridge.queue()
        deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            state=bridge.status()
            if state['status'] not in ('대기 중','수집 중'):
                return state if state.get('sources') else None
            time.sleep(1)
        return None

    def request(self,method,path,**kwargs):
        tls=getattr(self,'_tls',None)
        if tls is None:
            self._tls=tls=threading.local()
        session=getattr(tls,'session',None)
        if session is None:
            session=requests.Session()
            tls.session=session
        response=session.request(method,self.origin+'/api/desk'+path,headers=self.headers,timeout=(10,45),allow_redirects=False,**kwargs)
        if response.status_code>=300: raise RuntimeError(f'웹 동기화 HTTP {response.status_code}')
        return response

    def heartbeat(self,state='ready',message='수집 PC가 연결되어 있습니다.'):
        self.request('PUT','/agent',json={'state':state,'message':message})

    def publish(self,snapshot):
        for f in snapshot['files']:
            if f['id'] in self.uploaded: continue
            path=RAW/f['name']
            if path.parent.resolve()!=RAW.resolve(): raise ValueError('Unexpected file path')
            self.request('PUT','/file/'+f['id'],data=path.read_bytes())
            self.uploaded.add(f['id'])
            self.cache.write_text(json.dumps(sorted(self.uploaded)),encoding='utf-8')
        self.request('PUT','/snapshot',json=snapshot)
        temp=DATA/'web_snapshot.tmp';temp.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8');temp.replace(DATA/'web_snapshot.json')

    def run_job(self,job):
        if job['mode']=='profit-period':
            self.run_profit_period(job)
            return
        started=time.monotonic()
        errors=[];used_cache=False
        self.request('PUT','/job/'+job['id'],json={'state':'running','message':'공식 API 자료를 확인하고 있습니다. 이어서 화면·지원 엑셀과 AI 분석을 확인합니다.'})
        if job['mode'] in ('quick','full'):
            api_path=DATA/'api_snapshot.json'
            previous=json.loads(api_path.read_text(encoding='utf-8')) if api_path.exists() else {}
            age=(now()-datetime.fromisoformat(previous['fetched_at'])).total_seconds() if previous else 1e9
            if age>=300 or 'product_details' not in previous:
                try:
                    creds=load_credentials()
                    if not creds: raise RuntimeError('쿠팡 API 키가 없습니다.')
                    api=CoupangReader(**creds).collect()
                    if api.get('product_price_errors'):
                        errors.append(f"상품 상세 {api['product_price_errors']}건의 가격 갱신에 실패했습니다. 수집 시각을 확인해 주세요.")
                except Exception as ex: errors.append(str(ex) if isinstance(ex,RuntimeError) else 'API 갱신 실패. 이전 성공 자료 유지.')
            else: used_cache=True
        if job['mode']=='full':
            self.request('PUT','/job/'+job['id'],json={'state':'running','message':'쿠팡윙 화면·지원 엑셀의 갱신을 확인하고 있습니다. 미연결 원본은 유지됩니다.'})
            marker=DATA/'web_full_collect.json'
            previous=json.loads(marker.read_text()) if marker.exists() else {}
            age=time.time()-previous.get('time',0) if previous.get('complete') and previous.get('collector')=='aside-direct-v2' else 1e9
            if age>=3600:
                try:
                    from src.browser_collect import collect
                    result=collect()
                    if result['status']!='수집 완료' and getattr(self,'period_bridge',None) and self.period_bridge.status()['connected']:
                        chrome_state=self.chrome_full()
                        if chrome_state and chrome_state.get('status')=='수집 완료':
                            result={'status':'수집 완료','issues':[]}
                    if result['status']!='수집 완료':
                        errors.append(' / '.join(result['issues'])+'. 이전 검증 자료 유지.')
                    else: marker.write_text(json.dumps({'time':time.time(),'complete':True,'collector':'aside-direct-v2'}))
                except Exception as ex: errors.append(str(ex) if isinstance(ex,RuntimeError) else '화면 수집 실패. 이전 성공 자료 유지.')
            else: used_cache=True
        self.request('PUT','/job/'+job['id'],json={'state':'running','message':'AI API 분석을 준비하고 있습니다.' if job['mode']=='ai' else '원본을 대조하고 있습니다. 유료 AI 분석은 새로 요청하지 않습니다.'})
        snapshot=build_snapshot()
        if job['mode']=='ai':
            # The published view includes the privately stored product-cost master.
            context_snapshot=self.request('GET','').json().get('snapshot') or snapshot
            snapshot['ai']=advice(context_snapshot)
        else:
            previous_advice=DATA/'ai_advice.json'
            snapshot['ai']=json.loads(previous_advice.read_text(encoding='utf-8')) if previous_advice.exists() else {'status':'unavailable','message':'AI API 분석은 별도 요청 시 실행됩니다.'}
        if job['mode']=='ai' and snapshot['ai']['status']!='ready': errors.append(snapshot['ai']['message'])
        self.publish(snapshot)
        self.request('PUT','/job/'+job['id'],json={'state':'partial' if errors else 'complete','message':' / '.join(errors) if errors else ('연결된 수집 대상의 확인을 마쳤습니다. 미연결 자료와 자료별 기준 시각은 수집 현황에서 확인하세요.'+(' 최근 수집 자료 일부를 재사용했습니다.' if used_cache else '')),'duration_seconds':round(time.monotonic()-started)})

    def run_profit_period(self,job):
        from datetime import date, timedelta
        from src.aside_collector import collect
        from src.finance import parse_settlement
        from src.collector_relay import write_json
        path='/job/'+job['id']
        requested=job.get('range') or {}
        start,end=requested.get('start'),requested.get('end')
        try:
            start_date,end_date=date.fromisoformat(start),date.fromisoformat(end)
            valid=(start_date.isoformat()==start and end_date.isoformat()==end and
                   date(2024,10,1)<=start_date<=end_date<=now().date()-timedelta(days=1))
        except (ValueError,TypeError): valid=False
        if not valid:
            self.request('PUT',path,json={'state':'failed','message':'Wing에서 조회할 수 없는 기간입니다.'})
            return
        self.request('PUT',path,json={'state':'running','message':'선택한 기간을 쿠팡 Wing에서 조회하고 있습니다.'})
        try:
            range_={'start':start,'end':end}
            def verify(result):
                source=result['sources'][0]
                if source['status']!='수집 완료':raise ValueError(source['status'])
                row=parse_settlement(source['text'],source['captured_at'],'Wing 기간 직접 조회')
                if (row['start'],row['end'])!=(start,end):raise ValueError('Wing이 표시한 조회기간이 다릅니다.')
                return source,row
            try:
                result=collect(kinds=['settlement'],settlement_range=range_)
                source,row=verify(result)
            except (ValueError,RuntimeError,OSError) as error:
                self.request('PUT',path,json={'state':'running','message':'Aside에서 조회하지 못해 연결된 Chrome 수집기를 확인합니다.'})
                result=self.chrome_period(range_)
                if not result:
                    self.request('PUT',path,json={'state':'failed','message':'Wing 기간 조회 실패: '+str(error)[:120]+' · Aside 로그인 또는 Chrome 수집기 연결을 확인해 주세요.'})
                    return
                try:
                    source,row=verify(result)
                except (ValueError,KeyError,TypeError) as chrome_error:
                    self.request('PUT',path,json={'state':'failed','message':'Chrome Wing 조회 실패: '+str(chrome_error)[:120]+' · 이전 원본은 그대로 유지합니다.'})
                    return
            source={**source,'period_query':True}
            # Keep the full refresh status of unrelated sources. Only replace
            # settlement after the selected range and financial totals agree.
            write_json(DATA/('browser_snapshot_period_'+job['id']+'.json'),{'received_at':result['received_at'],'sources':[source]})
            # Keep the global view's last successful settlement and source state.
            snapshot=build_snapshot()
            if not any(item['start']==start and item['end']==end and item['captured_at']==row['captured_at'] for item in snapshot['finance']):
                raise ValueError('Exact range not in verified snapshot')
            previous_advice=DATA/'ai_advice.json'
            snapshot['ai']=json.loads(previous_advice.read_text(encoding='utf-8')) if previous_advice.exists() else {'status':'unavailable'}
            self.publish(snapshot)
        except (ValueError,OSError,RuntimeError,requests.RequestException):
            self.request('PUT',path,json={'state':'failed','message':'Wing 기간 원본을 읽거나 검증하지 못했습니다. 이전 자료를 유지합니다.'})
            return
        self.request('PUT',path,json={'state':'complete','message':'선택한 기간의 Wing 원본을 검증해 반영했습니다.'})

    def run_chat(self,turn):
        from concurrent.futures import ThreadPoolExecutor
        from src.desk_chat import answer
        path='/chat/'+turn['id']
        if time.time()-datetime.fromisoformat(turn['created_at'].replace('Z','+00:00')).timestamp()>180:
            self.request('PUT',path,json={'state':'failed','message':'질문 요청이 만료됐습니다. 다시 질문해 주세요.'});return
        self.request('PUT',path,json={'state':'running','message':'연결된 자료 전체와 이전 대화를 검토하고 있습니다.'})
        try:
            # Read the same published snapshot seen by other PCs. Do not silently
            # collect new Wing data or pay for another advice generation here.
            cache=DATA/('chat_reply_'+turn['id']+'.json')
            if cache.exists(): reply=json.loads(cache.read_text(encoding='utf-8'))
            else:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    f_snap=pool.submit(self.request,'GET','')
                    f_hist=pool.submit(self.request,'GET','/chat/context/'+turn['id'])
                    f_mem=pool.submit(self.request,'GET','/chat/memory')
                    snapshot=f_snap.result().json()['snapshot']
                    history=f_hist.result().json()
                    memory=f_mem.result().json()['records']
                reply=answer(snapshot,turn['question'],history['recent'],memory,related_history=history['related'])
                reply={
                    **reply,
                    'answer_origin':'아르곤(Antigravity) 핵심 요약',
                    'data_note':'',
                    'facts':[],
                    'suggestions':[],
                    'uncertainties':[],
                    'followups':[],
                    'sources':[],
                    'related_questions':[],
                }
                cache.write_text(json.dumps(reply,ensure_ascii=False),encoding='utf-8')
            self.request('PUT',path,json={'state':'complete','message':'운영 자료에 근거해 답변했습니다.','reply':reply})
        except Exception as ex:
            message=str(ex) if isinstance(ex,RuntimeError) and not isinstance(ex,requests.RequestException) else 'AI 답변을 완료하지 못했습니다. 잠시 후 다시 질문해 주세요.'
            self.request('PUT',path,json={'state':'failed','message':message})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--configure',action='store_true');parser.add_argument('--once',action='store_true');parser.add_argument('--local',action='store_true');parser.add_argument('--no-ai',action='store_true');args=parser.parse_args()
    if args.configure:
        # Pipe input only. Never echo the access token or save it in source.
        import getpass
        data=json.loads(getpass.getpass('Private connection JSON (hidden): ') if sys.stdin.isatty() else sys.stdin.readline())
        if data['origin']!='https://'+ALLOWED_HOST or not data.get('token'): raise ValueError('Invalid site credential')
        _windows_keyring().set_password(SERVICE,'active',json.dumps(data))
        print('Private Site connection saved in Windows Credential Locker.',flush=True);return
    lock=socket.socket()
    try: lock.bind(('127.0.0.1',18761 if not args.local else 18762))
    except OSError: print('Collector already running.',flush=True);return
    sync=Sync('http://127.0.0.1:3100' if args.local else None)
    if not args.local and not args.once:sync.start_period_bridge()
    stopped=threading.Event()
    def pulse():
        while not stopped.is_set():
            try: sync.heartbeat()
            except requests.RequestException: pass
            except RuntimeError: pass
            stopped.wait(25)
    thread=threading.Thread(target=pulse,daemon=True);thread.start()
    try:
        snapshot=build_snapshot()
        if args.no_ai:
            p=DATA/'ai_advice.json';snapshot['ai']=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'status':'unavailable','message':'AI 분석 대기 중'}
        else: snapshot['ai']=advice(snapshot)
        sync.publish(snapshot);print('Snapshot and original files synchronized.',flush=True)
        if args.once:return
        def chat_loop():
            while not stopped.is_set():
                try:
                    for turn in sync.request('GET','/chat/queue').json()['turns']: sync.run_chat(turn)
                except Exception: pass
                stopped.wait(1.2)
        # Independent from refresh jobs: a slow workbook download must not block
        # an ordinary conversation about the already published evidence.
        threading.Thread(target=chat_loop,daemon=True).start()
        while True:
            try:
                jobs=sync.request('GET','/queue').json()['jobs']
                for job in jobs:
                    if time.time()-datetime.fromisoformat(job['created_at'].replace('Z','+00:00')).timestamp()>900:
                        sync.request('PUT','/job/'+job['id'],json={'state':'failed','message':'수집 PC가 연결되기 전에 요청이 만료됐습니다. 다시 새로고침해 주세요.'});continue
                    try: sync.run_job(job)
                    except Exception:
                        sync.request('PUT','/job/'+job['id'],json={'state':'failed','message':'수집 또는 동기화 실패. 이전 자료를 유지합니다.'})
            except Exception: pass
            stopped.wait(15)
    finally: stopped.set();lock.close()

if __name__=='__main__':main()
