import {type DataRow} from './metric-data';
export type Decision = {id:string;label:string;priority:'먼저 확인'|'판단 보류';title:string;fact:string;action:string;stop:string;metric:string;sourceIds:string[];signature:string};
const num=(v:number)=>v.toLocaleString('ko-KR',{maximumFractionDigits:1});
export function decisions(s:DataRow):Decision[]{
  const inventory:DataRow[]=s.inventory||[], returns:DataRow[]=s.returns||[], result:Decision[]=[];
  const add=(decision:Omit<Decision,'signature'>,evidence:unknown)=>result.push({...decision,signature:JSON.stringify([decision.fact,decision.action,evidence])});
  const inbound=inventory.filter(r=>r.restock_alert && typeof r.stock_inbound==='number' && r.restock_rec_qty>0 && r.stock_inbound>=r.restock_rec_qty);
  if(inbound.length){const first=inbound[0];add({id:'inbound-overlap',label:'중복 발주 점검',priority:'먼저 확인',title:`입고 검토 ${inbound.length}개 항목에 이미 입고 예정이 있습니다`,
    fact:`${first.product_name} / ${first.option_name}: 권장 입고 ${num(first.restock_rec_qty)}개, 입고 예정 ${num(first.stock_inbound)}개. 입고 예정이 권장 수량 이상인 항목만 셌습니다.`,
    action:'발주하기 전에 기존 입고의 실제 도착일·수량을 대조하세요. 확정된 입고가 있는지 공급처와 입고 예약에서 확인합니다.',
    stop:'권장 수량이 입고 예정을 이미 반영했는지 미확인입니다. 두 수량을 자동 차감하거나 발주 취소로 연결하지 마세요.',metric:'inbound_overlap',sourceIds:['inventory']},inbound.map(r=>[r.option_id,r.grade,r.stock_inbound,r.restock_rec_qty]));}
  const stockouts=inventory.filter(r=>r.out_of_stock && typeof r.rev_7d==='number' && r.rev_7d>0);
  if(stockouts.length)add({id:'selling-stockout',label:'판매 흐름과 재고 연결',priority:'먼저 확인',title:`최근 판매가 있는 품절 상품 ${stockouts.length}개 항목`,
    fact:`최근 7일 판매금액이 양수이면서 현재 엑셀 판매가능재고가 0인 상품·옵션·등급별 항목입니다.`,
    action:'최근 판매가 있던 옵션부터 입고 예정과 실제 판매 중단 여부를 확인하세요. 판매가 없던 품절 항목과 구분해 살펴봅니다.',
    stop:'품절로 발생한 손실 매출을 뜻하지 않습니다. 판매가능재고 기준 시각과 현재 판매 상태가 다르면 판단을 보류하세요.',metric:'selling_stockout',sourceIds:['inventory']},stockouts.map(r=>[r.option_id,r.grade,r.rev_7d,r.stock_available]));
  const overdue=returns.filter(r=>r.overdue);
  if(overdue.length)add({id:'overdue-return',label:'회수·보상 대조',priority:'먼저 확인',title:`장기 회수 ${overdue.length}건의 처리 근거를 확인하세요`,
    fact:`원본에서 90일 이상 회수중인 접수 건은 ${overdue.length}건입니다. 최장 경과일은 ${num(Math.max(...overdue.map(r=>r.elapsed_days)))}일입니다.`,
    action:'해당 접수 내역의 회수 완료, 보상 내역, 정산 반영을 함께 대조하고 이미 처리된 건을 제외하세요.',
    stop:'현재 확보한 자료만으로 미보상 여부나 받을 금액을 확정할 수 없습니다.',metric:'overdue_returns',sourceIds:['returns','compensation']},overdue.map(r=>[r.option_id,r.request_date,r.elapsed_days,r.process_status]));
  const missing=inventory.filter(r=>r.unit_cost==null).length;
  if(missing)add({id:'missing-cost',label:'수익 판단의 선행 조건',priority:'판단 보류',title:`매입원가 ${missing}개 항목을 채워야 실제 수익을 판단할 수 있어요`,
    fact:`매입원가가 비어 있는 상품·옵션·등급별 항목이 ${missing}개입니다. 원가 0원이 입력된 항목과 구분했습니다.`,
    action:'최근 판매금액이 큰 상품의 매입원가부터 입력하고 수수료·물류·반품·기타 비용의 동일 기간 적용 여부를 대조하세요.',
    stop:'윙 표시 이익이나 ROAS만 보고 순이익·광고 증액 여부를 확정하지 마세요.',metric:'missing_costs',sourceIds:['inventory','finance','ads']},inventory.filter(r=>r.unit_cost==null).map(r=>[r.option_id,r.grade]));
  return result;
}
export function salesVelocity(s:DataRow,threshold:number){
  return (s.inventory||[]).filter((r:DataRow)=>typeof r.rev_30d==='number' && r.rev_30d>0 && typeof r.rev_7d==='number' && r.rev_7d>=0).map((r:DataRow)=>{
    const daily7=r.rev_7d/7,daily30=r.rev_30d/30,change=(daily7/daily30-1)*100;
    return {...r,daily7,daily30,change,direction:change>=threshold?'상승':change<=-threshold?'하락':'기준 이내'};
  }).sort((a:DataRow,b:DataRow)=>Math.abs(b.change)-Math.abs(a.change));
}
export function adScenario(ads:DataRow|null|undefined,marginPercent:number,plannedSpend:number){
  if(!ads || !Number.isFinite(ads.sales) || !Number.isFinite(ads.spend) || ads.sales<=0 || ads.spend<=0 ||
    !Number.isFinite(marginPercent) || marginPercent<=0 || marginPercent>100 || !Number.isFinite(plannedSpend) || plannedSpend<0)return null;
  const margin=marginPercent/100;
  return {breakEvenRoas:100/margin,requiredMargin:ads.spend/ads.sales*100,
    modeledContribution:ads.sales*margin-ads.spend,
    // Holding the same ROAS is an explicit scenario assumption, not a forecast.
    scenarioSales:plannedSpend*ads.sales/ads.spend,scenarioContribution:plannedSpend*ads.sales/ads.spend*margin-plannedSpend,
    breakEvenSales:plannedSpend/margin};
}
