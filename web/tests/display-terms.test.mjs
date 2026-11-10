import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const output=ts.transpileModule(readFileSync(new URL('../lib/display-terms.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {readableTerms}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
test('legacy count language becomes product item language',()=>{assert.equal(readableTerms('원가 미입력 43행. SKU·등급 행 기준'),'원가 미입력 43개 항목. 상품·옵션·등급별 항목 기준')});
test('ordinary Korean words remain intact',()=>{assert.equal(readableTerms('실행·진행·집행·행동·행사'), '실행·진행·집행·행동·행사')});
