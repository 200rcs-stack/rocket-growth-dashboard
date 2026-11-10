"""Regression checks for retained originals, schema drift, and private API writes."""
import json
import os
from pathlib import Path
import subprocess
import time

import pytest
import pandas as pd
from config import RAW, ROOT
from src import file_loader, parsers
from src.ad_performance import FILENAME


def test_changed_download_name_preserves_both_versions(monkeypatch, tmp_path):
    raw=tmp_path/'raw';downloads=tmp_path/'downloads';raw.mkdir();downloads.mkdir()
    name='inventory_health_sku_info_20261027090000.xlsx'
    (raw/name).write_bytes(b'original verified contents')
    os.utime(raw/name,(time.time()-20,time.time()-20))
    incoming=downloads/name;incoming.write_bytes(b'updated report contents')
    os.utime(incoming,(time.time()-10,time.time()-10))
    monkeypatch.setattr(file_loader,'RAW',raw);monkeypatch.setattr(file_loader,'DOWNLOADS',downloads)
    copied=file_loader.sync_downloads()
    assert len(copied)==1
    assert (raw/name).read_bytes()==b'original verified contents'
    assert (raw/copied[0]).read_bytes()==b'updated report contents'
    assert file_loader.sync_downloads()==[]
    monkeypatch.setattr(file_loader,'parse_inventory',lambda p:pd.DataFrame([{'content':p.read_bytes()}]))
    monkeypatch.setattr(file_loader,'record_file',lambda *_:None)
    monkeypatch.setattr(file_loader,'load_settlement_exports',lambda *_:([],[]))
    data=file_loader.load_data()
    assert data['inventory'].iloc[0]['content']==b'updated report contents'
    assert next(f['name'] for f in data['files'] if f['active'])==copied[0]


def test_all_preserved_inventory_headers_remain_supported():
    paths=list(RAW.glob('inventory_health_sku_info_*.xlsx'))
    assert paths
    for path in paths:
        assert parsers.valid_inventory_header(parsers.rows(path)[:2]),path.name


def test_ad_report_versions_keep_the_same_reporting_period():
    name='A123_pa_daily_vendorItem_20261001_20261025'
    original=FILENAME.fullmatch(name+'.xlsx')
    version=FILENAME.fullmatch(name+'_'+'a'*64+'.xlsx')
    assert version and original and version.groups()==original.groups()
    assert not FILENAME.fullmatch(name+'_unverified.xlsx')


@pytest.mark.parametrize('row,left,right',[(0,10,12),(1,10,11),(0,15,16),(1,22,23)])
def test_changed_metric_or_period_headers_fail_closed(monkeypatch,row,left,right):
    raw=[parsers.INVENTORY_HEADER.copy(),parsers.INVENTORY_SUBHEADER.copy()]
    raw[row][left],raw[row][right]=raw[row][right],raw[row][left]
    monkeypatch.setattr(parsers,'rows',lambda *_:raw)
    with pytest.raises(ValueError,match='헤더'):
        parsers.parse_inventory(Path('changed.xlsx'))


def test_api_job_pagination_and_write_validation():
    # Run actual TypeScript after transpilation, with an in-memory R2 substitute.
    script=r'''
import fs from 'node:fs';import assert from 'node:assert/strict';import ts from 'typescript';
const source=fs.readFileSync('lib/desk-api.ts','utf8');
const compilerOptions={module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022};
const importUrl=name=>'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(fs.readFileSync('lib/'+name+'.ts','utf8'),{compilerOptions}).outputText).toString('base64');
const code=ts.transpileModule(source.replace(/from '\.\/([\w-]+)'/g,(_,name)=>'from '+JSON.stringify(importUrl(name))),{compilerOptions}).outputText;
const {deskApi}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const values=new Map();
for(let i=0;i<1005;i++){const id=String(i).padStart(13,'0');values.set('jobs/'+id,{id,state:i===1004?'queued':'complete',created_at:new Date().toISOString()});}
const bucket={async list({prefix,cursor}){const all=[...values.keys()].filter(k=>k.startsWith(prefix)).sort();const start=Number(cursor||0);const keys=all.slice(start,start+1000);return {objects:keys.map(key=>({key})),truncated:start+1000<all.length,cursor:String(start+1000)};},async get(key){const value=values.get(key);return value?{json:async()=>value}:null;},async put(key,value){values.set(key,JSON.parse(value));}};
const req=(path,body,method='PUT')=>new Request('https://desk.test/api/desk'+path,{method,headers:{'Content-Type':'application/json'},body:typeof body==='string'?body:JSON.stringify(body)});
let response=await deskApi(new Request('https://desk.test/api/desk'),bucket);
assert.equal((await response.json()).jobs[0].id,'0000000001004');
response=await deskApi(new Request('https://desk.test/api/desk/queue'),bucket);
assert.equal((await response.json()).jobs[0].id,'0000000001004');
response=await deskApi(req('/refresh',{mode:'quick'},'POST'),bucket);
assert.equal((await response.json()).job.id,'0000000001004');
assert.equal(values.size,1005);
assert.equal((await deskApi(req('/agent','{broken'),bucket)).status,400);
assert.equal((await deskApi(req('/agent',null),bucket)).status,400);
assert.equal((await deskApi(req('/agent',{message:'x'.repeat(17000)}),bucket)).status,413);
assert.equal((await deskApi(req('/snapshot',{schema:1,sources:[],inventory:[{secretKey:'must not persist'}],files:[]}),bucket)).status,400);
assert.equal((await deskApi(req('/snapshot',{schema:1,sources:[],inventory:[],files:[],ai:{OPENAI_API_KEY:'must not persist'}}),bucket)).status,400);
assert.equal(values.has('snapshot.json'),false);
assert.equal((await deskApi(req('/snapshot',{schema:1,sources:[],inventory:[{option_id:'123',stock_available:2}],files:[]}),bucket)).status,200);
const cross=req('/agent',{state:'ready'});cross.headers.set('Origin','https://untrusted.test');
assert.equal((await deskApi(cross,bucket)).status,403);
values.set('snapshot.json',{schema:1,sources:[],inventory:[],files:[],finance:[{start:'2026-10-01',end:'2026-10-26',revenue:926140,expenses:-995827,compensation:0,profit:-69687}]});
const first=await (await deskApi(new Request('https://desk.test/api/desk'),bucket)).json();
assert.equal(first.snapshot.profit.net_profit,null);
assert.equal((await deskApi(req('/profit-costs',{basis:first.snapshot.profit.basis,cogs:0,extra:0,confirmed:false},'POST'),bucket)).status,400);
assert.equal((await deskApi(req('/profit-costs',{basis:'stale',cogs:0,extra:0,confirmed:true},'POST'),bucket)).status,409);
assert.equal((await deskApi(req('/profit-costs',{basis:first.snapshot.profit.basis,cogs:0,extra:0,confirmed:true},'POST'),bucket)).status,200);
const final=await (await deskApi(new Request('https://desk.test/api/desk'),bucket)).json();
assert.equal(final.snapshot.profit.net_profit,-69687);
assert.equal((await deskApi(req('/profit-costs',{basis:first.snapshot.profit.basis,reset:true},'POST'),bucket)).status,200);
assert.equal((await (await deskApi(new Request('https://desk.test/api/desk'),bucket)).json()).snapshot.profit.net_profit,null);
assert.equal([...values.keys()].filter(k=>k.startsWith('profit-cost-history/')).length,1);
await deskApi(req('/job/0000000001004',{state:'running',message:'collecting'}),bucket);
await deskApi(req('/job/0000000001004',{state:'partial',message:'source failed',duration_seconds:35}),bucket);
assert.equal(values.get('jobs/0000000001004').duration_seconds,35);
assert.ok(values.get('jobs/0000000001004').started_at);
console.log(JSON.stringify({ok:true}));
'''
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT/'web',capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['ok']
