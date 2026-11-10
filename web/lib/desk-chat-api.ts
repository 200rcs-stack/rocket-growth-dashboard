// The enclosing Site is owner-private. The existing Sites boundary authenticates
// the browser and local collector; no model credentials enter this runtime.
const json=(body:unknown,status=200)=>Response.json(body,{status,headers:{'Cache-Control':'private, no-store'}});
const pending=(turn:any)=>turn&&['queued','running'].includes(turn.state);
const MEMORY='chat/memory/';
const TURNS='chat/turns/';
const RECENT=8;
const RELATED=4;
const recordId=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const inRange=(v:unknown,min:number,max:number,whole=false)=>typeof v==='number'&&Number.isFinite(v)&&v>=min&&v<=max&&(!whole||Number.isInteger(v));
const common=new Set(['이전','예전','지난','전에','지금','현재','질문','답변','대화','내용','기억','그때','다시','어떻게','얼마','알려줘','말해줘','했어','뭐야','뭔지','해줘','있어','맞아','같이','로켓그로스','왓니몰']);
function memoryTerms(question:string){
  const words=question.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu)??[];
  return new Set(words.map(word=>word.replace(/^([가-힣]{2,})(에서는|에서|으로|에게|까지|부터|에는|하고|은|는|이|가|을|를|과|와|도|에)$/,'$1')).filter(word=>word.length>=2&&!common.has(word)));
}
function relevance(query:Set<string>,question:string){
  const old=memoryTerms(question);
  let score=0;
  for(const term of query){
    if(old.has(term)) score+=Math.min(term.length,10);
    else if(term.length>=3&&[...old].some(word=>word.length>=3&&(word.includes(term)||term.includes(word)))) score+=1;
  }
  return score;
}
export async function chatApi(request:Request,bucket:R2Bucket,path:string,body:any):Promise<Response>{
  const read=async(key:string)=>(await bucket.get(key))?.json() as Promise<any> ?? null;
  if(path==='/chat/memory'&&request.method==='GET'){
    const {objects}=await bucket.list({prefix:MEMORY,limit:150});
    const records=(await Promise.all(objects.map(x=>read(x.key)))).filter(Boolean).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
    return json({records});
  }
  if(path==='/chat/memory'&&request.method==='PUT'){
    const {id,remove,name,quantity,unit_cny,tax_krw,freight_cny,freight_basis,approximate_freight,exchange_rate}=body;
    if(typeof id!=='string'||!recordId.test(id))return json({error:'메모 식별자를 확인해 주세요.'},400);
    const key=MEMORY+id;
    if(remove===true){await bucket.delete(key);return json({ok:true});}
    if(typeof name!=='string'||!name.trim()||name.trim().length>100||/[\x00-\x1f]/.test(name)||!inRange(quantity,1,1e8,true)||!inRange(unit_cny,0,1e8)||!inRange(tax_krw,0,1e10,true)||!inRange(freight_cny,0,1e8)||!['lot','unit','unknown'].includes(freight_basis)||typeof approximate_freight!=='boolean'||!(exchange_rate===null||inRange(exchange_rate,0.0001,10000)))return json({error:'이름, 수량, 매입 단가, 세금과 물류비를 확인해 주세요. 환율은 모르면 비워 두세요.'},400);
    if(!(await read(key))&&(await bucket.list({prefix:MEMORY,limit:100})).objects.length>=100)return json({error:'메모를 100건까지 저장할 수 있습니다.'},409);
    const record={id,name:name.trim(),quantity,unit_cny,tax_krw,freight_cny,freight_basis,approximate_freight,exchange_rate,updated_at:new Date().toISOString()};
    await bucket.put(key,JSON.stringify(record));
    return json({record});
  }
  const objects=async(startAfter?:string)=>{
    let cursor:string|undefined;const items:R2Object[]=[];
    do{
      // R2 supports include, although the installed worker declarations omit it.
      const options={prefix:TURNS,limit:1000,include:['customMetadata'],...(cursor?{cursor}:startAfter?{startAfter}:{})};
      const page=await bucket.list(options);
      items.push(...page.objects);
      cursor=page.truncated?page.cursor:undefined;
    }while(cursor);
    return items.sort((a,b)=>b.key.localeCompare(a.key));
  };
  const turns=async()=>Promise.all((await objects()).slice(0,40).reverse().map(x=>read(x.key)));
  if(/^\/chat\/context\/\d{13}-[a-f0-9-]{36}$/.test(path)&&request.method==='GET'){
    const currentKey=TURNS+path.split('/').pop();
    const current=await read(currentKey);
    if(!current)return json({error:'대화 요청 없음'},404);
    const earlier=(await objects()).filter(x=>x.key<currentKey);
    // Old deployments retained at most forty turns and did not index them.
    // Read those records directly so the remaining history still participates.
    const legacy=earlier.filter(x=>!x.customMetadata?.state).slice(0,40);
    const oldTurns=new Map(await Promise.all(legacy.map(async x=>[x.key,await read(x.key)] as const)));
    const state=(x:R2Object)=>x.customMetadata?.state??oldTurns.get(x.key)?.state;
    const recentKeys=earlier.filter(x=>state(x)==='complete').slice(0,RECENT).map(x=>x.key);
    const recentSet=new Set(recentKeys);
    const query=memoryTerms(current.question);
    const best=earlier.filter(x=>!recentSet.has(x.key)&&['complete','failed'].includes(state(x)))
      .map(x=>({key:x.key,score:relevance(query,x.customMetadata?.question??oldTurns.get(x.key)?.question??'')}))
      .filter(x=>x.score>=2).sort((a,b)=>b.score-a.score||b.key.localeCompare(a.key)).slice(0,RELATED);
    const load=async(keys:string[])=>(await Promise.all(keys.map(key=>oldTurns.get(key)??read(key)))).filter(Boolean);
    const [recent,related]=await Promise.all([load(recentKeys.reverse()),load(best.map(x=>x.key))]);
    return json({recent,related});
  }
  if(path==='/chat'&&request.method==='GET'){
    const all=await turns();
    return json({turns:all.filter(Boolean).map(turn=>pending(turn)&&Date.now()-Date.parse(turn.created_at)>180000?{...turn,state:'failed',message:'응답 시간이 지났습니다. 다시 질문해 주세요.'}:turn)});
  }
  if(path==='/chat'&&request.method==='POST'){
    if(body.billing_mode!=='api')return json({error:'API 대화는 별도 과금입니다. 사용 방식을 확인해 주세요.'},400);
    if(typeof body.question!=='string'||!body.question.trim()||body.question.length>2000||typeof body.request_id!=='string'||!/^[a-f0-9-]{36}$/.test(body.request_id))return json({error:'질문은 2000자 이내로 입력해 주세요.'},400);
    const mapping=await read('chat/requests/'+body.request_id);
    if(mapping){const turn=await read('chat/turns/'+mapping.id);if(turn)return json({turn},202);}
    const [agent,snapshot,all]=await Promise.all([read('agent.json'),read('snapshot.json'),turns()]);
    if(!agent||Date.now()-Date.parse(agent.last_seen)>90000)return json({error:'수집 PC가 연결되어야 AI가 답할 수 있습니다. 저장된 지표는 계속 볼 수 있어요.'},503);
    if(!snapshot)return json({error:'먼저 운영 자료를 연결해 주세요.'},503);
    if(all.some(turn=>pending(turn)&&Date.now()-Date.parse(turn.created_at)<180000))return json({error:'이전 질문에 답변 중입니다. 답변을 받은 뒤 이어서 질문해 주세요.'},409);
    if(all.filter(turn=>Date.now()-Date.parse(turn.created_at)<60000).length>=6)return json({error:'잠시 뒤 이어서 질문해 주세요.'},429);
    const id=Date.now()+'-'+crypto.randomUUID();
    const turn={id,question:body.question.trim(),state:'queued',created_at:new Date().toISOString(),message:'운영 자료를 읽고 답변을 준비합니다.'};
    await bucket.put(TURNS+id,JSON.stringify(turn),{customMetadata:{state:'queued'}});
    await bucket.put('chat/requests/'+body.request_id,JSON.stringify({id}));
    return json({turn},202);
  }
  if(path==='/chat/queue'&&request.method==='GET'){
    const latest=await objects(TURNS+String(Date.now()-86_400_000));
    const queued=latest.filter(x=>!x.customMetadata?.state||['queued','running'].includes(x.customMetadata.state));
    return json({turns:(await Promise.all(queued.slice(0,40).reverse().map(x=>read(x.key)))).filter(pending)});
  }
  if(/^\/chat\/[0-9a-f-]+$/.test(path)&&request.method==='PUT'){
    const key=TURNS+path.split('/').pop(),old=await read(key);
    if(!old)return json({error:'대화 요청 없음'},404);
    if(!['running','complete','failed'].includes(body.state))return json({error:'대화 상태 확인 실패'},400);
    if(!pending(old))return json({ok:true}); // terminal updates are idempotent
    if(body.state==='complete'&&(!body.reply||typeof body.reply.answer!=='string'||!Array.isArray(body.reply.facts)||!Array.isArray(body.reply.sources)))return json({error:'답변 형식 확인 실패'},400);
    const customMetadata:Record<string,string>={state:body.state};
    if(body.state!=='running')customMetadata.question=old.question.length>360?old.question.slice(0,270)+' '+old.question.slice(-89):old.question;
    await bucket.put(key,JSON.stringify({...old,state:body.state,message:String(body.message||'').slice(0,700),...(body.state==='complete'?{reply:body.reply}:{}),updated_at:new Date().toISOString()}),{customMetadata});
    return json({ok:true});
  }
  return json({error:'대화 요청을 찾을 수 없습니다.'},404);
}
