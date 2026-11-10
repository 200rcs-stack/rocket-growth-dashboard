export type ProfitRow=Record<string,any>;
const finite=(v:any):v is number=>typeof v==='number'&&Number.isFinite(v);
export function profitBasis(finance:ProfitRow){
  // Capture clocks may change without changing an accounting observation.
  return JSON.stringify(['profit-v1',finance.start,finance.end,finance.revenue,finance.expenses,finance.compensation,finance.profit]);
}
export function profitData(snapshot:ProfitRow,costs:ProfitRow|null=null){
  const f=snapshot?.finance?.[0];
  if(!f||![f.revenue,f.expenses,f.compensation,f.profit].every(finite)||!f.start||!f.end)return {available:false,net_profit:null,missing:['동일 기간의 매출·비용 원본이 필요합니다.']};
  const basis=profitBasis(f),income=f.revenue+f.compensation,wingCost=-f.expenses,beforeCogs=income-wingCost;
  const reconciled=Math.abs(beforeCogs-f.profit)<1;
  const costComponents=[{key:'ads',label:'광고비',description:'윙 수익 현황에 반영된 광고 비용',amount:finite(f.ads)?-f.ads:null},
    {key:'fulfillment',label:'물류비',description:'윙에서 집계한 물류 비용',amount:finite(f.fulfillment)?-f.fulfillment:null},
    {key:'commission',label:'판매 수수료',description:'상품 판매에 따른 수수료',amount:finite(f.commission)?-f.commission:null}];
  const partsComplete=costComponents.every(part=>part.amount!==null);
  const partsSum=costComponents.reduce((sum,part)=>sum+(part.amount??0),0);
  if(partsComplete&&Math.abs(wingCost-partsSum)>=1)costComponents.push({key:'unmatched',label:'나머지 비용·조정',description:'세부 원본과 추가 대조가 필요한 차액',amount:wingCost-partsSum});
  const matching=costs?.basis===basis;
  const cogs=matching&&finite(costs?.cogs)?costs.cogs:null,extra=matching&&finite(costs?.extra)?costs.extra:null;
  const complete=reconciled&&cogs!==null&&extra!==null&&costs?.confirmed===true;
  return {available:true,basis,start:f.start,end:f.end,captured_at:f.captured_at,revenue:f.revenue,other_income:f.compensation,total_income:income,wing_cost:wingCost,before_cogs:beforeCogs,
    cogs,extra,total_cost:complete?wingCost+cogs+extra:null,net_profit:complete?income-wingCost-cogs-extra:null,cost_components:costComponents,cost_parts_complete:partsComplete,
    reconciled,matching:!!matching,stale_costs:!!costs&&!matching,confirmed:complete,
    status:complete?'입력 기준 순이익 · 마감 미확정':'순이익 확인 필요',
    missing:[...(!reconciled?['윙 표시 이익과 매출·비용·보상 합계가 일치하지 않습니다.']:[]),...(cogs===null?['같은 기간에 판매한 상품의 매출원가가 필요합니다.']:[]),...(extra===null?['윙 비용 외 추가 비용의 확인이 필요합니다.']:[]),...(costs&&!matching?['매출·비용 원본 또는 기간이 바뀌어 입력값 재확인이 필요합니다.']:[])],
    cost_inputs:matching?costs:null,source_ids:['finance']};
}
