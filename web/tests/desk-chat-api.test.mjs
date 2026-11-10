import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const output=ts.transpileModule(readFileSync(new URL('../lib/desk-chat-api.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {chatApi}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
function storage(seed={}){const data=new Map(Object.entries(seed));const metadata=new Map();return {data,metadata,async get(k){return data.has(k)?{json:async()=>data.get(k)}:null},async put(k,v,options){data.set(k,JSON.parse(v));metadata.set(k,options?.customMetadata)},async delete(k){data.delete(k);metadata.delete(k)},async list({prefix,startAfter}){return {objects:[...data.keys()].filter(k=>k.startsWith(prefix)&&(!startAfter||k>startAfter)).map(key=>({key,customMetadata:metadata.get(key)})),truncated:false}}}}
const request=(method)=>new Request('https://desk.test/api/desk/chat',{method});
const body={billing_mode:'api',question:'판매금액 차이를 알려줘',request_id:'12345678-1234-1234-1234-123456789abc'};
const seed=()=>({'agent.json':{last_seen:new Date().toISOString()},'snapshot.json':{schema:1}});
test('offline collector refuses new paid generation but retains readable history',async()=>{
 const bucket=storage();assert.equal((await chatApi(request('POST'),bucket,'/chat',body)).status,503);
 assert.deepEqual(await (await chatApi(request('GET'),bucket,'/chat')).json(),{turns:[]});
});
test('repeated transport request is idempotent and the next prompt cannot overlap',async()=>{
 const bucket=storage(seed());const first=await (await chatApi(request('POST'),bucket,'/chat',body)).json();
 const repeated=await (await chatApi(request('POST'),bucket,'/chat',body)).json();assert.equal(first.turn.id,repeated.turn.id);
 assert.equal((await chatApi(request('POST'),bucket,'/chat',{...body,request_id:'22345678-1234-1234-1234-123456789abc'})).status,409);
});
test('completed turn is durable and terminal writes are idempotent',async()=>{
 const bucket=storage(seed());const {turn}=await (await chatApi(request('POST'),bucket,'/chat',body)).json();
 const reply={answer:'기준이 다릅니다.',facts:[],sources:[]};
 assert.equal((await chatApi(request('PUT'),bucket,'/chat/'+turn.id,{state:'complete',reply})).status,200);
 await chatApi(request('PUT'),bucket,'/chat/'+turn.id,{state:'failed',message:'late failure'});
 const saved=await (await chatApi(request('GET'),bucket,'/chat')).json();assert.equal(saved.turns[0].state,'complete');assert.deepEqual(saved.turns[0].reply,reply);
});
test('old unanswered requests show failure rather than an endless spinner',async()=>{
 const bucket=storage({'chat/turns/old':{state:'queued',created_at:'2020-01-01T00:00:00Z'}});
 const result=await (await chatApi(request('GET'),bucket,'/chat')).json();assert.equal(result.turns[0].state,'failed');
});
test('oversize prompts and malformed completion are rejected',async()=>{
 const bucket=storage(seed());assert.equal((await chatApi(request('POST'),bucket,'/chat',{...body,question:'x'.repeat(2001)})).status,400);
 const {turn}=await (await chatApi(request('POST'),bucket,'/chat',body)).json();assert.equal((await chatApi(request('PUT'),bucket,'/chat/'+turn.id,{state:'complete',reply:{}})).status,400);
});
test('private import notes round-trip independently of chats and product costs',async()=>{
 const bucket=storage(seed());const memo={id:body.request_id,name:'텐트 수입분',quantity:100,unit_cny:7.5,tax_krw:50000,freight_cny:20,freight_basis:'unknown',approximate_freight:true,exchange_rate:null};
 assert.equal((await chatApi(request('PUT'),bucket,'/chat/memory',{...memo,quantity:0})).status,400);
 assert.equal((await chatApi(request('PUT'),bucket,'/chat/memory',memo)).status,200);
 const result=await (await chatApi(request('GET'),bucket,'/chat/memory')).json();
 assert.equal(result.records[0].exchange_rate,null);assert.equal(result.records[0].freight_basis,'unknown');assert.equal(result.records[0].unit_cny,7.5);
 assert.equal(bucket.data.has('product-costs.json'),false);
 await chatApi(request('PUT'),bucket,'/chat/memory',{id:memo.id,remove:true});
 assert.deepEqual((await (await chatApi(request('GET'),bucket,'/chat/memory')).json()).records,[]);
});
test('an earlier related question survives the visible window and is retrieved beside recent context',async()=>{
 const bucket=storage(seed());
 const base=Date.now()-86400000;
 const keyFor=i=>'chat/turns/'+(base+i)+'-12345678-1234-1234-1234-123456789abc';
 for(let i=0;i<46;i++){
  const key=keyFor(i),question=i===0?'비상용 텐트 중국 물류비가 얼마였지?':i===1?'비상용 텐트 통관 원가를 계산해줘':'반품 내역 확인';
  const state=i===1?'failed':'complete';
  bucket.data.set(key,{id:key.split('/').at(-1),state,question,created_at:new Date(base+i).toISOString()});
  if(i!==1)bucket.metadata.set(key,{state,question}); // one legacy record
 }
 const {turn}=await (await chatApi(request('POST'),bucket,'/chat',{...body,question:'전에 물어본 비상용 텐트 물류비 기억해?'})).json();
 assert.ok(bucket.data.has(keyFor(0)));
 const context=await (await chatApi(request('GET'),bucket,'/chat/context/'+turn.id)).json();
 assert.equal(context.recent.length,8);
 assert.deepEqual(context.related.map(x=>x.question),['비상용 텐트 중국 물류비가 얼마였지?','비상용 텐트 통관 원가를 계산해줘']);
 assert.ok(!(await (await chatApi(request('GET'),bucket,'/chat')).json()).turns.some(x=>x.id===keyFor(0).split('/').at(-1)));
 assert.equal((await (await chatApi(request('GET'),bucket,'/chat/queue')).json()).turns[0].id,turn.id);
});
