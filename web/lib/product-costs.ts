type Row=Record<string,any>;
export const costKey=(r:Row)=>JSON.stringify([String(r.option_id??'').trim(),String(r.grade??'').trim()]);
export const costBasis=(s:Row)=>{
 const text=JSON.stringify(['inventory-cost-v1',...(s.inventory||[]).map((r:Row)=>[costKey(r),r.source_file,r.rev_30d,r.qty_30d]).sort((a:any,b:any)=>String(a[0]).localeCompare(String(b[0])))]);
 // Compact change detector, not an authentication token. Authorization is enforced by Sites.
 let hash=BigInt('14695981039346656037');for(const byte of new TextEncoder().encode(text))hash=BigInt.asUintN(64,(hash^BigInt(byte))*BigInt('1099511628211'));
 return 'inventory-cost-v1:'+hash.toString(16);
};
const finite=(v:any):v is number=>typeof v==='number'&&Number.isFinite(v);
const sum=(rows:Row[],field:string)=>rows.length&&rows.every(r=>finite(r[field]))?rows.reduce((a,r)=>a+r[field],0):null;
export function costAnalytics(s:Row){
 const rows=(s.inventory||[]).map((r:Row)=>{
  const cost=finite(r.unit_cost)&&r.unit_cost>=0?r.unit_cost:null;
  const covered=cost!==null&&r.cost_sales_confirmed===true;
  const cogs=covered&&finite(r.qty_30d)&&r.qty_30d>=0?cost*r.qty_30d:null;
  const gross=cogs!==null&&finite(r.rev_30d)?r.rev_30d-cogs:null;
  const margin=gross!==null&&r.rev_30d>0?gross/r.rev_30d*100:null;
  const value=(q:any)=>cost!==null&&finite(q)&&q>=0?cost*q:null;
  return {...r,report_cogs:cogs,gross_difference:gross,gross_margin:margin,
   average_price:finite(r.qty_30d)&&r.qty_30d>0&&finite(r.rev_30d)?r.rev_30d/r.qty_30d:null,
   markup:gross!==null&&cogs!==null&&cogs>0?gross/cogs*100:null,
   cost_only_roas:margin!==null&&margin>0?10000/margin:null,
   stock_cost:value(r.stock_available),inbound_cost:value(r.stock_inbound),long_stock_cost:value(r.long_stock),
   restock_cost:r.restock_alert?value(r.restock_rec_qty):null};
 });
 const matched=rows.filter((r:Row)=>r.gross_difference!==null),stock=rows.filter((r:Row)=>r.stock_cost!==null);
 const revenue=sum(matched,'rev_30d'),cogs=sum(matched,'report_cogs'),gross=sum(matched,'gross_difference');
 const full=rows.length>0&&matched.length===rows.length;
 const stockFull=rows.length>0&&stock.length===rows.length;
 const margin=revenue!==null&&revenue>0&&gross!==null?gross/revenue*100:null;
 return {rows,total:rows.length,entered:rows.filter((r:Row)=>r.unit_cost!==null).length,matched:matched.length,full,stock_full:stockFull,
  revenue,cogs,gross,margin,markup:cogs!==null&&cogs>0&&gross!==null?gross/cogs*100:null,
  cost_only_roas:margin!==null&&margin>0?10000/margin:null,
  stock_cost:sum(stock,'stock_cost'),stock_covered:stock.length,
  inbound_cost:sum(rows.filter((r:Row)=>r.inbound_cost!==null),'inbound_cost'),
  long_stock_cost:sum(rows.filter((r:Row)=>r.long_stock_cost!==null),'long_stock_cost'),
  restock_cost:sum(rows.filter((r:Row)=>r.restock_cost!==null),'restock_cost'),
  negative_count:matched.filter((r:Row)=>r.gross_difference<0).length,
  note:'재고 보고서의 지난 30일·번들 제외 범위. 입력 단위원가를 판매수량에 적용한 참고 계산이며, 수수료·광고·물류·환불·세금 차감 전입니다. 윙 수익 현황의 기간·범위와 달라 자동 합산하지 않습니다.'};
}
export function withProductCosts(snapshot:Row,master:Row|null){
 const basis=costBasis(snapshot),records=master?.records||{},inventory=(snapshot.inventory||[]).map((r:Row)=>{
  const record=records[costKey(r)];
  return {...r,source_unit_cost:r.unit_cost,unit_cost:record?record.unit_cost:r.unit_cost??null,
   cost_updated_at:record?.updated_at??null,cost_origin:record?'사용자 입력':r.unit_cost!=null?'기존 원가 자료':'미입력',
   cost_sales_confirmed:!!record&&record.report_basis===basis&&record.confirmed===true};
 });
 const result={...snapshot,inventory,summary:{...snapshot.summary,missing_costs:inventory.filter((r:Row)=>r.unit_cost==null).length},
  product_cost_master:{revision:master?.revision??'',basis,updated_at:master?.updated_at??null}};
 return {...result,cost_analysis:costAnalytics(result)};
}
export function validateCostChanges(snapshot:Row,body:Row){
 if(!Array.isArray(body.entries)||!body.entries.length||body.entries.length>2000||typeof body.revision!=='string'||typeof body.basis!=='string'||body.confirmed!==true)throw Error('원가 입력과 판매분 적용 확인이 필요합니다.');
 if(body.basis!==costBasis(snapshot))throw Error('보고서가 바뀌었습니다. 새 자료를 확인한 뒤 다시 저장해 주세요.');
 const known=new Set((snapshot.inventory||[]).map(costKey)),seen=new Set<string>();
 return body.entries.map((r:Row)=>{
  if(!r||typeof r.option_id!=='string'||!/^\d{1,30}$/.test(r.option_id)||typeof r.grade!=='string'||r.grade.length>100)throw Error('옵션 ID·등급을 확인해 주세요.');
  const key=costKey(r);if(!known.has(key))throw Error('현재 보고서에 없는 옵션·등급입니다.');if(seen.has(key))throw Error('중복된 옵션·등급이 있습니다.');seen.add(key);
  if(r.unit_cost!==null&&(!finite(r.unit_cost)||r.unit_cost<0||r.unit_cost>1e9||Math.abs(Math.round(r.unit_cost*100)-r.unit_cost*100)>0.00001))throw Error('원가는 0~10억 원, 소수 둘째 자리까지 입력해 주세요.');
  return {key,unit_cost:r.unit_cost};
 });
}
