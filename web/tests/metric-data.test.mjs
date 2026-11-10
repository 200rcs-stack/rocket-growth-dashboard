import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
const source=readFileSync(new URL('../lib/metric-data.ts',import.meta.url),'utf8');
const output=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {metricData,sortedMetricRows,strictSum}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const snapshot={summary:{revenue30:75,api_stock:9,restock:1,overdue_returns:1,return_cases:2},
 inventory:[{option_id:'a',product_name:'상품 A',option_name:'흰색',grade:'새상품',rev_30d:100,restock_alert:true,doc_days:2,long_stock:3,unit_cost:null},
 {option_id:'a',product_name:'상품 A',option_name:'흰색',grade:'반품상품',rev_30d:-25,doc_days:null,long_stock:0,unit_cost:0},
 {option_id:'b',product_name:'상품 B',rev_30d:null,doc_days:4,long_stock:null,unit_cost:10}],
 api_inventory:[{option_id:'a',stock:4},{option_id:'c',stock:5}],
 returns:[{product_name:'상품 A',process_status:'회수중',overdue:true,elapsed_days:120},{product_name:'상품 B',process_status:'완료',overdue:false,elapsed_days:5}],
 finance:[{revenue:100,expenses:-120,profit:-20,start:'2026-10-01',end:'2026-10-26'},{revenue:80,expenses:-60,profit:20}],ads:null};
test('API stock is not duplicated by SKU grade joins and unmatched options remain visible',()=>{
 const metric=metricData(snapshot,'api_stock');assert.equal(metric.value,9);assert.equal(metric.rows.length,2);assert.equal(strictSum(metric.rows,'stock'),9);assert.equal(metric.rows[0].product_name,'상품 A');assert.match(metric.rows[1].product_name,/미연결/);
});
test('sales preserves negative adjustments and does not invent missing quantities',()=>{
 const metric=metricData(snapshot,'revenue30');assert.equal(metric.rows[1].rev_30d,-25);assert.equal(strictSum(metric.rows,'rev_30d'),null);assert.equal(strictSum([{v:2},{v:0},{v:-1}],'v'),1);assert.equal(strictSum([],'v'),null);
});
test('restock and overdue drill-downs use the same flags as the published summaries',()=>{
 for(const [key,field] of [['restock','restock'],['overdue_returns','overdue_returns']]){const metric=metricData(snapshot,key);assert.equal(metric.rows.length,snapshot.summary[field]);assert.equal(metric.value,snapshot.summary[field]);}
});
test('null values remain last when sorting in either direction',()=>{
 const metric=metricData(snapshot,'revenue30');for(const ascending of [true,false]){const rows=sortedMetricRows(metric,'','rev_30d',ascending);assert.equal(rows.at(-1).option_id,'b');}assert.equal(sortedMetricRows(metric,'','rev_30d',true)[0].rev_30d,-25);
});
test('search covers displayed columns without mutating rows or the total',()=>{
 const metric=metricData(snapshot,'api_stock'),before=JSON.stringify(metric);assert.equal(sortedMetricRows(metric,'미연결','stock',false).length,1);assert.equal(metric.value,9);assert.equal(JSON.stringify(metric),before);
});
test('missing unit cost is distinct from an explicitly entered zero',()=>{const metric=metricData(snapshot,'missing_costs');assert.equal(metric.rows.length,1);assert.equal(metric.rows[0].unit_cost,null)});
test('long storage counts confirmed SKU rows and discloses excluded unknowns',()=>{const metric=metricData(snapshot,'long_stock');assert.equal(metric.value,1);assert.equal(metric.unit,'개 항목');assert.match(metric.explanation,/미확인인 1개 항목/);assert.equal(metricData({inventory:[{long_stock:null}]},'long_stock').value,null)});
test('finance uses latest observation without adding overlapping periods',()=>{const metric=metricData(snapshot,'finance_profit');assert.equal(metric.value,-20);assert.equal(metric.rows.length,1);assert.equal(metric.rows[0].expenses,-120)});
test('missing ads are not represented as zero performance',()=>{assert.equal(metricData(snapshot,'ad_spend').value,null);assert.deepEqual(metricData(snapshot,'ad_roas').rows,[])});
test('decision detail includes only the inbound overlap candidate',()=>{
 const metric=metricData({inventory:[{restock_alert:true,stock_inbound:100,restock_rec_qty:45},{restock_alert:true,stock_inbound:0,restock_rec_qty:5}],summary:{}},'inbound_overlap');assert.equal(metric.rows.length,1);assert.equal(metric.value,1);assert.equal(metric.rows[0].stock_inbound,100);
});
test('selling stockout detail excludes inactive and unknown sales rows',()=>{
 const metric=metricData({inventory:[{out_of_stock:true,rev_7d:100},{out_of_stock:true,rev_7d:0},{out_of_stock:true,rev_7d:null},{out_of_stock:false,rev_7d:200}],summary:{}},'selling_stockout');assert.equal(metric.rows.length,1);assert.equal(metric.value,1);assert.equal(metric.rows[0].rev_7d,100);
});
