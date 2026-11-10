type Row=Record<string,any>;
export function sourceOverview(s:Row){
 const sources:Row[]=s.sources||[];
 const missing=sources.filter(r=>!r.time).length;
 const review=sources.filter(r=>r.time&&r.quality?.review_required).length;
 const current=sources.filter(r=>r.time&&!r.quality?.review_required).length;
 return {total:sources.length,missing,review,current,sorted:[...sources].sort((a,b)=>{
  const rank=(r:Row)=>!r.time?3:/실패|미수집|미완료/.test(r.status||'')?2:r.quality?.review_required?1:0;
  return rank(b)-rank(a)||(Date.parse(a.time)||0)-(Date.parse(b.time)||0);
 })};
}
export function returnOverview(s:Row){
 const rows:Row[]=s.returns||[],source=s.sources?.find((r:Row)=>r.id==='returns');
 const known=Array.isArray(s.returns)&&(rows.length>0||source?.count===0&&!!source.time);
 return {known,total:known?rows.length:null,overdue:known?rows.filter(r=>r.overdue===true).length:null,
  collecting:known?rows.filter(r=>r.process_status==='회수중').length:null,
  statuses:known?new Set(rows.map(r=>r.process_status||'상태 미확인')).size:null};
}
export function aiReview(s:Row,report:Row|undefined,now=Date.now()){
 if(!report)return '분석 자료 없음';
 const time=Date.parse(report.generated_at),sources:Row[]=s.sources||[];
 if(!Number.isFinite(time)||time>now)return '분석 시각 확인 필요';
 if(sources.some(r=>Number.isFinite(Date.parse(r.time))&&Date.parse(r.time)>time))return '분석 후 갱신된 자료 있음';
 if(sources.some(r=>r.quality?.review_required)||now-time>24*3600000)return '이전 분석 · 원본 재확인 필요';
 return null;
}
