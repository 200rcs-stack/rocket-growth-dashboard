import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const {outputText}=ts.transpileModule(readFileSync(new URL('../lib/wing-period.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
const {wingPresets,wingRange,exactWingRow}=await import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'));
const now=new Date('2026-11-09T12:00:00+09:00');
test('Wing date presets end yesterday in Korea and preserve calendar-month boundaries',()=>{
 assert.deepEqual(wingPresets(now),{
  week:{start:'2026-11-02',end:'2026-11-08'},
  last:{start:'2026-10-01',end:'2026-10-31'},
  month:{start:'2026-11-01',end:'2026-11-08'},
 });
 const newYear=new Date('2026-12-31T15:01:00Z');
 assert.deepEqual(wingPresets(newYear).last,{start:'2026-12-01',end:'2026-12-31'});
 assert.equal(wingRange(wingPresets(newYear).month.start,wingPresets(newYear).month.end,newYear),null);
});
test('custom dates reject future, nonexistent, reversed and pre-Wing dates',()=>{
 for(const [a,b] of [['2026-11-01','2026-11-09'],['2026-02-30','2026-03-01'],['2026-11-08','2026-11-01'],['2024-09-30','2024-10-01']])assert.equal(wingRange(a,b,now),null);
 assert.deepEqual(wingRange('2026-11-08','2026-11-08',now),{start:'2026-11-08',end:'2026-11-08'});
});
test('overlapping source records are never substituted or added together',()=>{
 const range=wingPresets(now).week;
 const old={...range,captured_at:'2026-11-09T04:00:00Z',revenue:1};
 const fresh={...old,captured_at:'2026-11-09T04:30:00Z',revenue:7};
 assert.equal(exactWingRow([old,{...fresh,start:'2026-11-01'},fresh],range),fresh);
 assert.equal(exactWingRow([{...fresh,start:'2026-11-01'}],range),undefined);
});
