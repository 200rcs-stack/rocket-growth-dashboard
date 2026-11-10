import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const output=ts.transpileModule(readFileSync(new URL('../lib/source-health.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {withCurrentSourceHealth}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const now=Date.parse('2026-10-27T08:00:00Z');
test('old business data ages independently of a fresh collector heartbeat',()=>{
 const input={sources:[{id:'inventory',time:'2026-10-27T04:00:00Z',status:'검증됨',quality:{review_required:false}}],quality:{review_required:0},manual:{sections:[{source_ids:['inventory'],source_review_required:false}]}};
 const result=withCurrentSourceHealth(input,now);assert.equal(result.quality.review_required,1);assert.equal(result.sources[0].quality.age_hours,4);assert.equal(result.manual.sections[0].source_review_required,true);assert.equal(input.sources[0].quality.review_required,false);
});
test('missing and future clocks cannot be represented as recent verified data',()=>{
 const result=withCurrentSourceHealth({sources:[{id:'a',time:null},{id:'b',time:'2026-10-28T00:00:00Z',status:'검증됨'}]},now);assert.equal(result.quality.review_required,2);assert.equal(result.sources[0].quality.age_hours,null);
});
test('current successful source stays recent while recent failures remain flagged',()=>{
 const result=withCurrentSourceHealth({sources:[{id:'a',time:'2026-10-27T07:00:00Z',status:'검증됨'},{id:'b',time:'2026-10-27T07:00:00Z',status:'갱신 실패'}]},now);assert.equal(result.sources[0].quality.review_required,false);assert.equal(result.sources[1].quality.review_required,true);
});
