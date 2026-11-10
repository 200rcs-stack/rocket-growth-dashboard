import type {DataRow} from './metric-data';
// Re-evaluate age when the page polls, even if the collector returns an unchanged
// snapshot. A fresh heartbeat must not make old business data look recent.
export function withCurrentSourceHealth(snapshot:DataRow,now=Date.now()):DataRow {
  const sources=(snapshot.sources||[]).map((source:DataRow)=>{
    const captured=source.time?Date.parse(source.time):NaN;
    const age=Number.isFinite(captured)?(now-captured)/3600000:null;
    const failed=/실패|필요|미완료|미수집|이전/.test(source.status||'미수집');
    const invalid=age==null || age<0;
    return {...source,quality:{...source.quality,age_hours:age==null?null:Math.round(age*10)/10,
      freshness:invalid?'기준 시각 확인 필요':age<=2?'최근 수집':'기준 시각 경과',
      review_required:!!source.quality?.review_required || failed || invalid || age>2}};
  });
  const requiresReview=(id:string)=>sources.find((source:DataRow)=>source.id===id)?.quality.review_required??true;
  return {...snapshot,sources,quality:{...snapshot.quality,review_required:sources.filter((source:DataRow)=>source.quality.review_required).length},
    ...(snapshot.manual?{manual:{...snapshot.manual,sections:snapshot.manual.sections.map((section:DataRow)=>({...section,source_review_required:section.source_ids.some(requiresReview)}))}}:{})};
}
