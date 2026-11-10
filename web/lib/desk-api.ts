import {chatApi} from './desk-chat-api';
import {profitData} from './profit-data';
import {exactWingRow,wingRange} from './wing-period';
import {withProductCosts,validateCostChanges} from './product-costs';
// The Site is owner-private. Sites dispatch authenticates both browser and service callers.
const json = (body: unknown, status = 200) => Response.json(body, {status, headers:{'Cache-Control':'no-store'}});
// Do not rely on Content-Length: streamed and compressed requests may omit it.
async function boundedJson(request: Request, limit: number) {
  if (!request.headers.get('content-type')?.startsWith('application/json')) throw new Error('415');
  if (Number(request.headers.get('content-length')) > limit) throw new Error('413');
  const reader=request.body?.getReader();
  if (!reader) throw new Error('400');
  const chunks:Uint8Array[]=[];let length=0;
  try {
    for (;;) {
      const {done,value}=await reader.read();if(done)break;
      length+=value.byteLength;
      if(length>limit){await reader.cancel();throw new Error('413');}
      chunks.push(value);
    }
    const bytes=new Uint8Array(length);let offset=0;
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
    const body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if(!body || typeof body!=='object' || Array.isArray(body))throw new Error('400');
    return body;
  } catch(error) {
    if(error instanceof Error && ['413','415'].includes(error.message))throw error;
    throw new Error('400');
  } finally {reader.releaseLock();}
}

function hasSensitiveKeys(body:unknown):boolean {
  const pending:unknown[]=[body];
  while(pending.length){
    const next=pending.pop();if(!next || typeof next!=='object')continue;
    for(const [key,value] of Object.entries(next)){
      if(/^(?:(?:(?:openai|coupang)_)?(?:access_?key|secret_?key|api_?key)|password|authorization|cookie|token|secret|(?:session|refresh|bearer)_?token|order_?no|order_?id|return_?no|inspection_?no|customer_?(?:name|phone|email|address)|recipient_?(?:name|phone|address))$/i.test(key))return true;
      if(value && typeof value==='object')pending.push(value);
    }
  }
  return false;
}
export async function deskApi(request: Request, bucket?: R2Bucket): Promise<Response> {
  if (!bucket) return json({error:'저장소를 준비하고 있습니다.'},503);
  const url = new URL(request.url);
  const path = url.pathname.replace('/api/desk','');
  if (!['GET','POST','PUT'].includes(request.method)) return json({error:'허용되지 않는 요청'},405);
  if (request.method !== 'GET') {
    const origin=request.headers.get('origin');
    if ((origin && origin !== url.origin) || request.headers.get('sec-fetch-site') === 'cross-site') return json({error:'요청 출처 확인 실패'},403);
  }
  const read = async(key:string):Promise<any> => (await bucket.get(key))?.json() ?? null;
  const periodCostKey=(start:string,end:string)=>'profit-costs-period/'+start+'_'+end+'.json';
  const readPeriodCosts=async(row:any)=>row
    ? await read(periodCostKey(row.start,row.end)) ?? await read('profit-costs.json')
    : null;
  // R2 list is lexicographic and paginated. Older requests must not hide new
  // jobs after the first thousand requests have accumulated.
  const jobObjects=async()=>{
    let cursor:string|undefined;const objects:R2Object[]=[];
    do {
      const page=await bucket.list({prefix:'jobs/',limit:1000,...(cursor?{cursor}:{})});
      objects.push(...page.objects);cursor=page.truncated?page.cursor:undefined;
    }while(cursor);
    return objects.sort((a,b)=>b.key.localeCompare(a.key));
  };
  let body:any;
  if(request.method!=='GET' && !/^\/file\/[a-f0-9]{64}$/.test(path)){
    try{body=await boundedJson(request,path==='/snapshot'?5_000_000:path==='/product-costs'?500_000:path.startsWith('/chat/')?200_000:16_384);}
    catch(error){const code=Number((error as Error).message);return json({error:code===413?'크기 제한':code===415?'JSON 필요':'자료 형식 확인 실패'},code);}
  }
  if(path==='/chat'||path.startsWith('/chat/')){
    if(request.method==='PUT'&&hasSensitiveKeys(body))return json({error:'답변에 포함할 수 없는 민감 필드'},400);
    return chatApi(request,bucket,path,body);
  }
  if (path==='' && request.method==='GET') {
    const [raw,agent,list,master] = await Promise.all([read('snapshot.json'),read('agent.json'),jobObjects(),read('product-costs.json')]);
    const costs=await readPeriodCosts(raw?.finance?.[0]);
    const snapshot=raw?withProductCosts(raw,master):null;
    const newest=list.slice(0,5);
    return json({snapshot:snapshot?{...snapshot,profit:profitData(snapshot,costs)}:snapshot,agent,jobs:await Promise.all(newest.map(x=>read(x.key))),access:{viewer_email:request.headers.get('oai-authenticated-user-email'),concurrent_viewing:true,stored_data_requires_collector:false}});
  }
  if(path==='/profit-period'&&request.method==='GET'){
    const range=wingRange(url.searchParams.get('start'),url.searchParams.get('end'));
    if(!range)return json({error:'쿠팡 Wing에서 조회할 수 있는 날짜를 선택해 주세요.'},400);
    const snapshot=await read('snapshot.json');
    const row=exactWingRow(snapshot?.finance,range);
    return json({row:row??null,profit:profitData({finance:row?[row]:[]},await readPeriodCosts(row))});
  }
  if(path==='/product-costs'&&request.method==='POST'){
    const raw=await read('snapshot.json');if(!raw)return json({error:'먼저 재고 자료를 연결해 주세요.'},409);
    let changes;try{changes=validateCostChanges(raw,body)}catch(error){return json({error:(error as Error).message},400)}
    const previous=await read('product-costs.json');
    if((previous?.revision??'')!==body.revision)return json({error:'다른 화면에서 원가를 저장했습니다. 최신 자료를 불러온 뒤 다시 입력해 주세요.'},409);
    const time=new Date().toISOString(),records={...previous?.records};
    for(const change of changes)records[change.key]={unit_cost:change.unit_cost,report_basis:body.basis,confirmed:true,updated_at:time};
    const master={revision:crypto.randomUUID(),updated_at:time,records};
    if(previous)await bucket.put('product-cost-history/'+Date.now()+'-'+crypto.randomUUID(),JSON.stringify(previous));
    await bucket.put('product-costs.json',JSON.stringify(master));return json({ok:true});
  }
  if(path==='/profit-costs'&&request.method==='POST'){
    const raw=await read('snapshot.json');
    const range=body.start||body.end?wingRange(body.start,body.end):null;
    if((body.start||body.end)&&!range)return json({error:'조회 기간이 올바르지 않습니다.'},400);
    const row=range?exactWingRow(raw?.finance,range):raw?.finance?.[0];
    const current=profitData({finance:row?[row]:[]});
    if(!current.available||current.basis!==body.basis)return json({error:'기간 또는 원본이 바뀌었습니다. 화면을 다시 확인해 주세요.'},409);
    const storage=periodCostKey(current.start,current.end);
    if(body.reset===true){
      const previous=await readPeriodCosts(row);
      if(previous)await bucket.put('profit-cost-history/'+Date.now()+'-'+crypto.randomUUID(),JSON.stringify(previous));
      const reset={basis:current.basis,cogs:null,extra:null,confirmed:false,updated_at:new Date().toISOString()};
      await bucket.put(storage,JSON.stringify(reset));return json({ok:true});
    }
    if(typeof body.basis!=='string'||body.basis.length>1000||!Number.isSafeInteger(body.cogs)||body.cogs<0||body.cogs>1e12||!Number.isSafeInteger(body.extra)||Math.abs(body.extra)>1e12||body.confirmed!==true)return json({error:'동일 기간의 비용과 확인 여부를 입력해 주세요.'},400);
    if(!current.reconciled)return json({error:'매출·비용 원본의 합계 대조가 필요합니다.'},409);
    const costs={basis:body.basis,cogs:body.cogs,extra:body.extra,confirmed:true,start:current.start,end:current.end,updated_at:new Date().toISOString()};
    await bucket.put(storage,JSON.stringify(costs));return json({ok:true,profit:profitData({finance:[row]},costs)});
  }
  if (path==='/refresh' && request.method==='POST') {
    if (!['quick','full','ai','profit-period'].includes(body.mode)) return json({error:'올바르지 않은 갱신 유형'},400);
    const range=body.mode==='profit-period'?wingRange(body.start,body.end):null;
    if(body.mode==='profit-period'&&!range)return json({error:'쿠팡 Wing에서 조회할 수 있는 날짜를 선택해 주세요.'},400);
    const list=await jobObjects();
    for (const o of list.slice(0,8)) {
      const job=await read(o.key) as {state:string;created_at:string;mode?:string;range?:{start:string;end:string}};
      if (job && ['queued','running'].includes(job.state) && Date.now()-Date.parse(job.created_at)<15*60*1000) {
        if(range&&(job.mode!=='profit-period'||job.range?.start!==range.start||job.range?.end!==range.end))return json({error:'다른 갱신이 진행 중입니다. 완료 후 다시 조회해 주세요.'},409);
        return json({job,message:'이미 갱신 요청이 있습니다.'},202);
      }
    }
    const id=Date.now().toString()+'-'+crypto.randomUUID();
    const job={id,mode:body.mode,...(range?{range}:{}),state:'queued',created_at:new Date().toISOString(),message:'이 PC 수집기의 응답을 기다립니다.'};
    await bucket.put('jobs/'+id,JSON.stringify(job));return json({job},202);
  }
  if (path==='/queue' && request.method==='GET') {
    const list=await jobObjects();
    const jobs=await Promise.all(list.reverse().map(x=>read(x.key)));
    return json({jobs:jobs.filter((x:any)=>x?.state==='queued')});
  }
  if (path==='/snapshot' && request.method==='PUT') {
    if (body.schema!==1 || !Array.isArray(body.sources) || !Array.isArray(body.inventory) || !Array.isArray(body.files)) return json({error:'자료 형식 확인 실패'},400);
    if(hasSensitiveKeys(body))return json({error:'웹 요약에 포함할 수 없는 민감 필드'},400);
    const content=JSON.stringify(body);
    if(content.length>5_000_000)return json({error:'크기 제한'},413);
    await bucket.put('snapshot.json',content);return json({ok:true});
  }
  if (path==='/agent' && request.method==='PUT') {
    await bucket.put('agent.json',JSON.stringify({last_seen:new Date().toISOString(),state:String(body.state).slice(0,100),message:String(body.message||'').slice(0,500)}));return json({ok:true});
  }
  if (/^\/job\/[0-9a-f-]+$/.test(path) && request.method==='PUT') {
    const key='jobs/'+path.split('/').pop();const old=await read(key) as any;
    if (!old) return json({error:'요청 없음'},404);
    if (!['running','complete','partial','failed'].includes(body.state)) return json({error:'상태 확인 실패'},400);
    const duration=typeof body.duration_seconds==='number'&&Number.isFinite(body.duration_seconds)&&body.duration_seconds>=0?Math.round(body.duration_seconds):undefined;
    await bucket.put(key,JSON.stringify({...old,state:body.state,message:String(body.message||'').slice(0,1000),...(body.state==='running'&&!old.started_at?{started_at:new Date().toISOString()}:{}),...(duration!==undefined?{duration_seconds:duration}:{}),updated_at:new Date().toISOString()}));return json({ok:true});
  }
  if (/^\/file\/[a-f0-9]{64}$/.test(path)) {
    const id=path.split('/').pop(); const key='files/'+id;
    if (request.method==='PUT') {
      if (Number(request.headers.get('content-length'))>50_000_000) return json({error:'파일 크기 제한'},413);
      const buffer=await request.arrayBuffer();
      if(buffer.byteLength>50_000_000)return json({error:'파일 크기 제한'},413);
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))).map(x=>x.toString(16).padStart(2,'0')).join('');
      if (hash!==id) return json({error:'파일 해시 불일치'},400);
      await bucket.put(key,buffer);return json({ok:true});
    }
    if(request.method==='GET') {
      const snap=await read('snapshot.json') as any;
      const item=snap?.files?.find((x:any)=>x.id===id);
      if(!item)return json({error:'원본 목록에 없는 파일'},404);
      const file=await bucket.get(key);if(!file)return json({error:'원본 동기화 대기 중'},404);
      return new Response(file.body,{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(item.name),'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}});
    }
  }
  return json({error:'찾을 수 없습니다.'},404);
}
