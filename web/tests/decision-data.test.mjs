import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const source=readFileSync(new URL('../lib/decision-data.ts',import.meta.url),'utf8');
const output=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {decisions,salesVelocity,adScenario}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
test('inbound overlap is an inspection case, not an automatic order subtraction',()=>{
 const rows=[{product_name:'상품',option_name:'주황',restock_alert:true,stock_inbound:100,restock_rec_qty:45,unit_cost:0},{restock_alert:true,stock_inbound:null,restock_rec_qty:4,unit_cost:0},{restock_alert:true,stock_inbound:0,restock_rec_qty:0,unit_cost:0}];
 const result=decisions({inventory:rows}).find(x=>x.id==='inbound-overlap');assert.ok(result);assert.match(result.title,/1개 항목/);assert.match(result.fact,/45개/);assert.match(result.fact,/100개/);assert.match(result.stop,/자동 차감/);
});
test('a review signature changes with material facts and ignores capture clock changes',()=>{
 const s={inventory:[{restock_alert:true,stock_inbound:100,restock_rec_qty:45,unit_cost:0}]};const signature=decisions(s)[0].signature;
 assert.equal(decisions({...s,generated_at:'later'})[0].signature,signature);s.inventory[0].stock_inbound=80;assert.notEqual(decisions(s)[0].signature,signature);
});
test('selling stockout requires positive recent sales and confirmed zero stock flag',()=>{
 const rows=[{out_of_stock:true,rev_7d:10,unit_cost:0},{out_of_stock:true,rev_7d:0,unit_cost:0},{out_of_stock:true,rev_7d:null,unit_cost:0},{out_of_stock:false,rev_7d:100,unit_cost:0}];assert.match(decisions({inventory:rows})[0].title,/1개 항목/);
});
test('sales velocity compares daily averages and excludes missing or nonpositive base',()=>{
 const s={inventory:[{option_id:'up',rev_7d:140,rev_30d:300},{option_id:'down',rev_7d:0,rev_30d:300},{rev_7d:null,rev_30d:300},{rev_7d:30,rev_30d:0},{rev_7d:10,rev_30d:-10}]};
 const rows=salesVelocity(s,30);assert.equal(rows.length,2);assert.equal(rows.find(r=>r.option_id==='up').change,100);assert.equal(rows.find(r=>r.option_id==='down').change,-100);assert.equal(rows.find(r=>r.option_id==='up').direction,'상승');
});
test('ad break-even and modeled contribution remain explicit assumptions',()=>{
 const a=adScenario({sales:1000,spend:200},20,100);assert.equal(a.requiredMargin,20);assert.equal(a.breakEvenRoas,500);assert.equal(a.modeledContribution,0);assert.equal(a.scenarioSales,500);assert.equal(a.scenarioContribution,0);assert.equal(a.breakEvenSales,500);
 assert.equal(adScenario({sales:1000,spend:200},10,100).modeledContribution,-100);
});
test('invalid or missing ad facts and invalid margins never produce a projected profit',()=>{
 for(const ads of [null,{sales:null,spend:100},{sales:0,spend:100},{sales:100,spend:0},{sales:-1,spend:100}])assert.equal(adScenario(ads,20,100),null);
 for(const m of [0,-1,101,NaN])assert.equal(adScenario({sales:100,spend:10},m,100),null);assert.equal(adScenario({sales:100,spend:10},20,-1),null);assert.equal(adScenario({sales:100,spend:10},20,0).scenarioContribution,0);
});
