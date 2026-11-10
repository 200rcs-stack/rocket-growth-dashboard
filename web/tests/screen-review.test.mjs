import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../lib/screen-review.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {sourceOverview,returnOverview,aiReview}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('missing returns remain unknown, verified empty reports may show zero, overdue counts follow records',()=>{
 assert.equal(returnOverview({}).total,null);
 assert.equal(returnOverview({returns:[],sources:[]}).total,null);
 assert.equal(returnOverview({returns:[],sources:[{id:'returns',count:0,time:'2026-10-27'}]}).total,0);
 const r=returnOverview({returns:[{process_status:'회수중',overdue:true},{process_status:'회수중',overdue:false},{process_status:'폐기',overdue:false}]});
 assert.equal(r.overdue,1);assert.equal(r.collecting,2);assert.equal(r.total,3);assert.equal(r.statuses,2);
});
test('source summaries separate missing clocks from stale sources and put failures first without mutating input',()=>{
 const s={sources:[{id:'current',time:'2026-10-29',status:'수집 완료',quality:{review_required:false}},{id:'stale',time:'2026-10-27',status:'수집 완료',quality:{review_required:true}},{id:'failed',time:'2026-10-28',status:'수집 실패',quality:{review_required:true}},{id:'missing'}]};
 const h=sourceOverview(s);assert.deepEqual([h.total,h.current,h.review,h.missing],[4,1,2,1]);assert.deepEqual(h.sorted.map(r=>r.id),['missing','failed','stale','current']);assert.equal(s.sources[0].id,'current');
});
test('AI reports are flagged after source updates, source failures, or aging; unknown timestamps never pass',()=>{
 const now=Date.parse('2026-10-29T12:00:00Z'),report={generated_at:'2026-10-29T11:00:00Z'};
 assert.equal(aiReview({sources:[{time:'2026-10-29T10:00:00Z'}]},report,now),null);
 assert.match(aiReview({sources:[{time:'2026-10-29T11:30:00Z'}]},report,now),/갱신된 자료/);
 assert.match(aiReview({sources:[{quality:{review_required:true}}]},report,now),/재확인/);
 assert.match(aiReview({},report,now+25*3600000),/이전 분석/);
 assert.match(aiReview({},{generated_at:'bad'},now),/시각 확인/);
 assert.match(aiReview({},{generated_at:'2099-01-01'},now),/시각 확인/);
});
