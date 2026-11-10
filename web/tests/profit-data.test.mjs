import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const output=ts.transpileModule(readFileSync(new URL('../lib/profit-data.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {profitData,profitBasis}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const f={start:'2026-10-01',end:'2026-10-26',revenue:926140,expenses:-995827,compensation:0,profit:-69687,captured_at:'2026-10-27T07:05:00+09:00'};
const s={finance:[f]};
test('missing COGS and external costs never become zero or confirmed net profit',()=>{
 const p=profitData(s);assert.equal(p.wing_cost,995827);assert.equal(p.before_cogs,-69687);assert.equal(p.total_cost,null);assert.equal(p.net_profit,null);assert.equal(p.confirmed,false);
});
test('explicit zero is valid after confirmation and original expense is not double-counted',()=>{
 const p=profitData(s,{basis:profitBasis(f),cogs:0,extra:0,confirmed:true});assert.equal(p.net_profit,-69687);assert.equal(p.total_cost,995827);
 const q=profitData(s,{basis:profitBasis(f),cogs:100000,extra:5000,confirmed:true});assert.equal(q.total_cost,1100827);assert.equal(q.net_profit,-174687);
});
test('income compensation is included separately and signed cost credits are preserved',()=>{
 const finance={...f,revenue:1000,expenses:-300,compensation:50,profit:750};const p=profitData({finance:[finance]},{basis:profitBasis(finance),cogs:100,extra:-20,confirmed:true});assert.equal(p.total_income,1050);assert.equal(p.total_cost,380);assert.equal(p.net_profit,670);
});
test('a new period or changed source balance invalidates previous inputs while a changed capture clock does not',()=>{
 const inputs={basis:profitBasis(f),cogs:100,extra:0,confirmed:true};assert.equal(profitData({finance:[{...f,end:'2026-10-27'}]},inputs).net_profit,null);assert.equal(profitData({finance:[{...f,revenue:10}]},inputs).net_profit,null);assert.equal(profitData({finance:[{...f,captured_at:'2026-10-28'}]},inputs).net_profit,-69787);
});
test('unbalanced or incomplete originals cannot produce net profit',()=>{
 const broken={...f,profit:0};assert.equal(profitData({finance:[broken]},{basis:profitBasis(broken),cogs:0,extra:0,confirmed:true}).net_profit,null);assert.equal(profitData({finance:[]}).net_profit,null);assert.equal(profitData({finance:[{...f,revenue:null}]}).net_profit,null);
});
test('cost explanation reconciles the exact original amounts without adding costs twice',()=>{
 const result=profitData({finance:[{...f,ads:-639324,fulfillment:-249624,commission:-106879}]});
 assert.deepEqual(result.cost_components.map(p=>p.amount),[639324,249624,106879]);
 assert.equal(result.cost_components.reduce((sum,p)=>sum+p.amount,0),995827);
 assert.equal(result.cost_parts_complete,true);
 const incomplete=profitData({finance:[f]});assert.equal(incomplete.cost_parts_complete,false);assert.equal(incomplete.cost_components[0].amount,null);
});
