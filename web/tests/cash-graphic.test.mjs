import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const output=ts.transpileModule(readFileSync(new URL('../lib/cash-graphic.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {cashGraphic}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const actual={total_income:926140,wing_cost:995827,cost_parts_complete:true,cost_components:[{key:'ads',amount:639324},{key:'fulfillment',amount:249624},{key:'commission',amount:106879}]};
test('donut shares and comparison rails use the same verified totals',()=>{
 const result=cashGraphic(actual);assert.equal(result.available,true);assert.ok(Math.abs(result.segments.reduce((sum,s)=>sum+s.share,0)-1)<1e-12);assert.equal(result.cost_width,100);assert.ok(result.income_width<100);assert.equal(Math.round(result.expense_ratio*10)/10,107.5);assert.equal(result.segments[1].offset,result.segments[0].share);
});
test('missing or unbalanced cost components never become a complete donut',()=>{
 for(const input of [{...actual,cost_parts_complete:false},{...actual,cost_components:[{key:'a',amount:1}]},{...actual,cost_components:[{key:'a',amount:null}]}]){const result=cashGraphic(input);assert.equal(result.available,false);assert.ok(result.segments.every(s=>s.share===null));}
});
test('negative credits and zero income do not produce misleading percentage slices',()=>{
 const result=cashGraphic({...actual,total_income:0,cost_components:[{key:'charge',amount:995837},{key:'credit',amount:-10}]});assert.equal(result.available,false);assert.equal(result.expense_ratio,null);assert.equal(cashGraphic({}).income_width,null);
});
