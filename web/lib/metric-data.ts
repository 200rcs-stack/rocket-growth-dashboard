export type DataRow = Record<string, any>;
export type MetricColumn = {key:string; label:string; format?:'money'|'days'|'percent'|'number'|'date'};
export type MetricData = {
  key:string; title:string; value:number|null; unit:string; sourceId:string;
  explanation:string; formula:string; caution:string; rows:DataRow[];
  columns:MetricColumn[]; sortKey:string; ascending?:boolean;
};
const column=(key:string,label:string,format?:MetricColumn['format']):MetricColumn=>({key,label,format});
const productColumns=[column('product_name','상품'),column('option_name','옵션'),column('option_id','옵션 ID'),column('grade','등급')];
export function strictSum(rows:DataRow[],key:string):number|null {
  if(!rows.length || rows.some(row=>typeof row[key]!=='number' || !Number.isFinite(row[key])))return null;
  return rows.reduce((total,row)=>total+row[key],0);
}
export function metricData(snapshot:DataRow,key:string):MetricData {
  const inventory:DataRow[]=snapshot.inventory||[], returns:DataRow[]=snapshot.returns||[];
  const summary=snapshot.summary||{}, finance=snapshot.finance?.[0], ads=snapshot.ads;
  const base={key,rows:inventory,columns:productColumns,sourceId:'inventory',unit:'개 항목',value:null,sortKey:'product_name',
    explanation:'수집한 원본에 포함된 범위입니다.',formula:'원본의 해당 항목을 확인합니다.',
    caution:'자료의 기준 시각을 확인하세요. 미확인 값은 0으로 대체하지 않습니다.'} as MetricData;
  switch(key){
    case 'inbound_overlap': {
      const metric=metricData(snapshot,'restock'),rows=metric.rows.filter(r=>typeof r.stock_inbound==='number' && r.restock_rec_qty>0 && r.stock_inbound>=r.restock_rec_qty);
      return {...metric,key,title:'입고 예정과 권장 수량 대조',value:inventory.length?rows.length:null,rows,
        explanation:'입고 검토 대상 중 입고 예정 수량이 권장 입고량 이상인 상품·옵션·등급별 항목만 보여줍니다.',
        formula:'입고 검토 조건에 해당하고, 입고 예정 ≥ 권장 입고량인 항목입니다. 기존 입고의 실제 도착 일정을 먼저 확인하세요.',
        caution:'권장 수량이 입고 예정을 이미 반영했는지 미확인입니다. 자동 차감·발주 취소를 뜻하지 않습니다.'};
    }
    case 'selling_stockout': {
      const metric=metricData(snapshot,'out_of_stock'),rows=metric.rows.filter(r=>typeof r.rev_7d==='number' && r.rev_7d>0);
      return {...metric,key,title:'최근 판매가 있는 품절 상품',value:inventory.length?rows.length:null,rows,
        explanation:'엑셀 판매가능재고가 0이고 최근 7일 판매금액이 양수인 상품·옵션·등급별 항목입니다. 미확인 매출 항목은 제외했습니다.',
        formula:'품절 항목 중 최근 7일 판매금액 > 0인 항목을 확인합니다. 예상 손실 매출은 계산하지 않습니다.',
        columns:[...productColumns.slice(0,2),column('rev_7d','7일 판매금액','money'),column('stock_available','판매가능','number'),column('stock_inbound','입고 예정','number'),...productColumns.slice(2)]};
    }
    case 'revenue30': return {...base,title:'재고 보고서 판매금액',value:summary.revenue30,unit:'원',
      explanation:'재고 엑셀에 포함된 상품·옵션·등급별 항목의 지난 30일 판매금액입니다. 원본에서 번들 매출은 제외합니다. 상품을 눌러 추가 지표를 확인하세요.',
      formula:'원본의 최근 30일 판매금액을 모든 상품·옵션·등급별 항목에 걸쳐 합산하며 번들 매출은 제외합니다.',
      caution:'정산 매출이나 API 주문금액과 조회기간·범위가 다릅니다. 음수 금액도 원본 그대로 포함합니다.',
      columns:[...productColumns.slice(0,2),column('rev_30d','30일 판매금액','money'),column('qty_30d','30일 판매수량','number'),column('rev_7d','7일 판매금액','money'),column('stock_available','판매가능재고','number'),...productColumns.slice(2)],sortKey:'rev_30d'};
    case 'api_stock': {
      const rows=(snapshot.api_inventory||[]).map((item:DataRow)=>{
        const matches=inventory.filter(r=>String(r.option_id)===String(item.option_id));
        return {...item,product_name:matches.length?[...new Set(matches.map(r=>r.product_name))].join(' / '):'엑셀 상품명 미연결',
          option_name:matches.length?[...new Set(matches.map(r=>r.option_name))].join(' / '):'—'};
      });
      return {...base,title:'판매가능재고 · 공식 API',value:summary.api_stock,unit:'개',sourceId:'api_inventory',rows,
        explanation:'공식 API로 조회한 전체 옵션별 판매가능재고입니다. 상품명은 옵션 ID가 일치하는 엑셀에서 연결했습니다.',
        formula:'API 전체 옵션의 totalOrderableQuantity 합계입니다. 옵션마다 한 번씩 계산합니다.',
        caution:'엑셀의 상품·옵션·등급별 항목과 범위가 달라 수량이 다를 수 있습니다. 상품명이 미연결이어도 API 재고 합계에는 포함됩니다.',
        columns:[column('product_name','연결 상품명'),column('option_name','옵션'),column('option_id','옵션 ID'),column('stock','판매가능재고','number')],sortKey:'stock'};
    }
    case 'restock': return {...base,title:'입고 검토 대상',value:summary.restock,rows:inventory.filter(r=>r.restock_alert),
      explanation:'재고가 리드타임 이내에 소진될 것으로 표시되고, 권장 입고량이 양수인 상품·옵션·등급별 항목입니다.',
      formula:'예상 재고일 ≤ 입고 리드타임, 권장 입고량 > 0. 미입력 리드타임에는 기본 14일을 사용합니다.',
      caution:'권장 수량은 발주 확정이 아닙니다. 실제 재고, 입고 예정, 판매 추이와 공급처 일정을 먼저 확인하세요.',
      columns:[...productColumns.slice(0,2),column('stock_available','판매가능','number'),column('stock_inbound','입고 예정','number'),column('doc_days','예상 재고일','days'),column('restock_rec_qty','권장 입고량','number'),column('lead_days','리드타임','days'),column('restock_rec_date','권장 입고일'),...productColumns.slice(2)],sortKey:'doc_days',ascending:true};
    case 'overdue_returns': return {...base,title:'90일 이상 회수중',value:summary.overdue_returns,unit:'건',sourceId:'returns',rows:returns.filter(r=>r.overdue),
      explanation:'반품 엑셀에서 접수 후 90일 이상 지나고 처리 상태가 회수중인 접수 건입니다.',
      formula:'원본의 회수중 상태와 접수 후 경과일 90일 이상을 함께 확인합니다. 상품 수량이 아닌 접수 건수입니다.',
      caution:'보상 미지급 확정이 아닙니다. 실제 회수·보상 처리와 정산 반영 여부를 원본으로 대조하세요.',
      columns:returnColumns(),sortKey:'elapsed_days'};
    case 'inventory_stock': return {...base,title:'엑셀 판매가능재고',value:summary.inventory_stock,unit:'개',
      explanation:'재고 엑셀에 포함된 상품·옵션·등급별 판매가능재고입니다.',formula:'모든 원본 항목의 판매가능재고 합계입니다.',
      columns:[...productColumns,column('stock_available','판매가능재고','number'),column('stock_inbound','입고 예정','number')],sortKey:'stock_available'};
    case 'out_of_stock': return {...base,title:'품절 상품',value:summary.out_of_stock,rows:inventory.filter(r=>r.out_of_stock),
      explanation:'엑셀 판매가능재고가 0인 상품·옵션·등급별 항목입니다.',formula:'판매가능재고가 정확히 0인 항목을 셉니다. 미확인 재고는 제외합니다.',
      columns:[...productColumns,column('stock_available','판매가능','number'),column('qty_30d','30일 판매','number'),column('stock_inbound','입고 예정','number'),column('restock_rec_qty','권장 입고','number')],sortKey:'qty_30d'};
    case 'missing_costs': return {...base,title:'매입원가 미입력',value:summary.missing_costs,rows:inventory.filter(r=>r.unit_cost==null),
      explanation:'매입원가가 입력되지 않아 수익성 판단을 보류해야 하는 상품·옵션·등급별 항목입니다.',formula:'매입원가가 비어 있는 항목을 셉니다. 원가 0원과 구분합니다.',
      caution:'매입원가·기타 비용·환불과 정산을 대조하기 전에는 순이익이나 손익분기 ROAS를 확정할 수 없습니다.',
      columns:[...productColumns,column('unit_cost','매입원가','money'),column('rev_30d','30일 판매금액','money'),column('stock_available','판매가능','number')],sortKey:'rev_30d'};
    case 'long_stock': {const rows=inventory.filter(r=>r.long_stock>0),missing=inventory.filter(r=>r.long_stock==null).length;return {...base,title:'61일 이상 보관 상품',value:inventory.some(r=>r.long_stock!=null)?rows.length:null,unit:'개 항목',rows,
      explanation:`61일 이상 보관 수량이 1개 이상 확인된 상품·옵션·등급별 항목입니다. 보관 수량이 미확인인 ${missing}개 항목은 집계에서 제외했습니다.`,formula:'61~120일 + 121~180일 + 181일 이상 보관 수량이 양수인 항목을 셉니다. 같은 상품도 옵션·상품등급이 다르면 별도 항목으로 셉니다입니다.',
      columns:[...productColumns,column('long_stock','61일 이상 합계','number'),column('age_61_120','61~120일','number'),column('age_121_180','121~180일','number'),column('age_181_plus','181일 이상','number'),column('storage_fee_mtd','당월 보관료','money')],sortKey:'long_stock'};}
    case 'storage_fee': return {...base,title:'당월 보관료 · 재고 엑셀',value:strictSum(inventory,'storage_fee_mtd'),unit:'원',
      explanation:'재고 보고서에 표시된 당월 누적 보관료입니다.',formula:'모든 상품·옵션·등급별 항목의 당월 보관료 합계입니다. 빈 값이 있으면 합계를 확정하지 않습니다.',
      caution:'정산 상세 보관비와 기준일·세금 기준이 다를 수 있습니다. 중복 합산하지 마세요.',
      columns:[...productColumns,column('storage_fee_mtd','당월 보관료','money'),column('long_stock','61일 이상 재고','number')],sortKey:'storage_fee_mtd'};
    case 'return_cases': case 'status_types': return {...base,title:key==='status_types'?'반품 처리 상태':'반품 접수 내역',value:key==='status_types'?(returns.length?new Set(returns.map(r=>r.process_status)).size:null):summary.return_cases,unit:key==='status_types'?'종':'건',sourceId:'returns',rows:returns,
      explanation:'확보한 반품 엑셀에 포함된 접수 내역입니다. 검색창에서 처리 상태와 반품 사유도 찾을 수 있습니다.',formula:'원본 포함 접수 건수 또는 처리 상태의 종류입니다. 수량(개)과 구분합니다.',
      caution:'현재 주문 건수로 나눠 반품률을 계산하지 않습니다. 고객·주문 식별정보는 이 목록에서 제외했습니다.',columns:returnColumns(),sortKey:'elapsed_days'};
    case 'ad_spend': case 'ad_sales': case 'ad_roas': return {...base,title:({ad_spend:'광고 집행비',ad_sales:'광고 전환매출',ad_roas:'광고 ROAS'} as DataRow)[key],value:ads?.[({ad_spend:'spend',ad_sales:'sales',ad_roas:'roas'} as DataRow)[key]]??null,unit:key==='ad_roas'?'%':'원',sourceId:'ads',rows:ads?[ads]:[],
      explanation:'광고센터 화면에 표시된 조회기간의 성과 요약입니다.',formula:'ROAS = 광고 전환매출 ÷ 집행 광고비 × 100. 화면의 값을 표시하며 반올림 차이가 있을 수 있습니다.',
      caution:'광고 전환매출은 전체 매출에 더하지 않습니다. ROAS는 이익률이 아니며, 상품별 상세 보고서와 기간·기여 기준이 다를 수 있습니다.',
      columns:[column('start','시작일'),column('end','종료일'),column('spend','집행 광고비','money'),column('sales','전환매출','money'),column('roas','ROAS','percent')],sortKey:'start'};
    case 'finance_revenue': case 'finance_expenses': case 'finance_profit': return {...base,title:({finance_revenue:'윙 표시 매출',finance_expenses:'윙 표시 비용',finance_profit:'윙 표시 이익 · 원가 차감 전'} as DataRow)[key],value:finance?.[({finance_revenue:'revenue',finance_expenses:'expenses',finance_profit:'profit'} as DataRow)[key]]??null,unit:'원',sourceId:'finance',rows:finance?[finance]:[],
      explanation:'마지막 검증에 성공한 윙 수익 현황입니다. 화면 갱신에 실패한 경우 이전 자료가 유지됩니다.',formula:'윙 표시 이익 = 매출 + 비용(음수) + 재고 보상. 아래 비용의 부호는 원본 그대로 표시합니다.',
      caution:'매입원가 등 외부 비용이 빠진 수치로 순이익이 아닙니다. 기간이 겹치는 과거 관측값은 합산하지 않습니다.',
      columns:[column('start','시작일'),column('end','종료일'),column('revenue','매출','money'),column('expenses','비용','money'),column('ads','광고비','money'),column('fulfillment','물류비','money'),column('commission','판매 수수료','money'),column('compensation','재고 보상','money'),column('profit','윙 표시 이익','money')],sortKey:'start'};
    default: throw new Error('지원하지 않는 지표: '+key);
  }
}
function returnColumns():MetricColumn[]{return [column('request_date','접수일','date'),column('product_name','상품'),column('option_id','옵션 ID'),column('process_status','처리 상태'),column('elapsed_days','접수 후 경과','days'),column('return_qty','반품 수량','number'),column('reason','반품 사유')];}
export function sortedMetricRows(metric:MetricData,query:string,sortKey:string,ascending:boolean):DataRow[]{
  const needle=query.trim().toLocaleLowerCase('ko-KR');
  return metric.rows.filter(row=>!needle || metric.columns.some(c=>String(row[c.key]??'').toLocaleLowerCase('ko-KR').includes(needle))).slice().sort((a,b)=>{
    const av=a[sortKey],bv=b[sortKey];
    const missing=(v:any)=>v==null || (typeof v==='number'&&!Number.isFinite(v));
    if(missing(av))return missing(bv)?0:1;if(missing(bv))return -1;
    const compare=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'ko-KR',{numeric:true});
    return ascending?compare:-compare;
  });
}
