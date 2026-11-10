import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const from=async name=>{const code=ts.transpileModule(readFileSync(new URL('../lib/'+name+'.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;return import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));};
const {familyIdentity,productFamilies}=await from('product-families');
const {clampFloating,floatingBounds,savedFloating}=await from('floating-position');
const {readDesk}=await from('desk-connection');
test('same product name keeps its color across options, grades, ordering and whitespace while records stay separate',()=>{
 const a={product_id:'1',option_id:'11',product_name:'가방   상품',grade:'NEW'},b={product_id:'2',option_id:'12',product_name:'가방 상품',grade:'반품'},c={product_id:'3',option_id:'13',product_name:'신발 상품'};
 assert.equal(familyIdentity(a),familyIdentity(b));assert.notEqual(familyIdentity(a),familyIdentity(c));const x=productFamilies([a,b,c]),y=productFamilies([c,b,a]);assert.deepEqual(x,y);assert.equal(Object.keys(x).length,2);assert.notEqual(x[familyIdentity(a)].label,x[familyIdentity(c)].label);assert.equal([a,b,c].length,3);
 const z=productFamilies([{product_name:'추가상품'},a,b,c]);assert.equal(x[familyIdentity(a)].color,z[familyIdentity(a)].color);
 assert.notEqual(familyIdentity({product_name:'미연결',option_id:'1'}),familyIdentity({product_name:'미연결',option_id:'2'}));
});
test('drag locations stay on screen and restore proportionally on another viewport',()=>{
 const b=floatingBounds(200,60,1200,800);assert.deepEqual(clampFloating({x:-500,y:9999},b),{x:12,y:728});assert.deepEqual(savedFloating({x:1,y:0},b),{x:988,y:12});assert.equal(savedFloating({x:10,y:0},b),null);assert.equal(savedFloating({x:'bad',y:0},b),null);assert.deepEqual(clampFloating({x:NaN,y:Infinity},b),{x:12,y:12});const small=floatingBounds(900,900,390,844);assert.deepEqual(clampFloating({x:100,y:100},small),{x:12,y:12});
});
test('each viewer reads independent cloud snapshots without waiting for a collector or owning a session lock',async()=>{
 let calls=0;const fetcher=async(url,options)=>{calls++;assert.equal(url,'/api/desk');assert.equal(options.credentials,'same-origin');return Response.json({snapshot:{inventory:[1]},agent:null});};const [a,b]=await Promise.all([readDesk(fetcher),readDesk(fetcher)]);assert.equal(calls,2);assert.deepEqual(a,b);assert.equal(a.agent,null);
});
test('auth HTML and forbidden account access produce recovery messages instead of an endless spinner',async()=>{
 for(const [response,kind] of [[new Response('<html>login</html>',{headers:{'content-type':'text/html'}}),'auth'],[new Response('',{status:401}),'auth'],[new Response('',{status:403}),'forbidden'],[new Response('',{status:503}),'server']])await assert.rejects(()=>readDesk(async()=>response),e=>e.kind===kind);
 await assert.rejects(()=>readDesk(async()=>{throw Error('offline')}),e=>e.kind==='network');
});
