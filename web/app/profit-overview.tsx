"use client";
import {useEffect,useState} from 'react';
import {Dialog} from 'radix-ui';
import {ArrowRight,ArrowUpRight,Check,Clock3,Info,Wallet,ChartNoAxesCombined,SlidersHorizontal,X} from 'lucide-react';
import {cashGraphic} from '../lib/cash-graphic';
import {profitData,type ProfitRow} from '../lib/profit-data';
import {exactWingRow,WING_MIN,wingPresets,wingRange,type WingRange} from '../lib/wing-period';
const won=(v:any)=>v==null?'확인 필요':Number(v).toLocaleString('ko-KR')+'원';
const stamp=(v?:string)=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})+' KST':'미확인';
export default function ProfitOverview({snapshot:s,onMetric,onSaved,periodControls=false,online=false,jobs=[]}:{snapshot:ProfitRow;onMetric:(key:string,row?:ProfitRow,profit?:ProfitRow)=>void;onSaved:()=>Promise<void>;periodControls?:boolean;online?:boolean;jobs?:ProfitRow[]}){
 const [mode,setMode]=useState<'week'|'last'|'month'|'custom'>('month'),[start,setStart]=useState(''),[end,setEnd]=useState('');
 const [periodCosts,setPeriodCosts]=useState<ProfitRow|null>(null),[periodMessage,setPeriodMessage]=useState(''),[pending,setPending]=useState(''),[sending,setSending]=useState(false);
 const presets=wingPresets(),candidate=mode==='custom'?{start,end}:presets[mode];
 const range=periodControls?wingRange(candidate.start,candidate.end):null;
 const row=range?exactWingRow(s.finance,range):null;
 const p=periodControls?profitData({finance:row?[row]:[]},periodCosts?.start===range?.start&&periodCosts?.end===range?.end?periodCosts:s.profit?.cost_inputs):s.profit||profitData(s);
 const [cogs,setCogs]=useState(''),[extra,setExtra]=useState(''),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const source=s.sources?.find((r:ProfitRow)=>r.id==='finance');
 const review=periodControls?Date.now()-Date.parse(p.captured_at||'')>7200000:source?.quality?.review_required;
 const [detailsOpen,setDetailsOpen]=useState(false);
 const readCosts=async (r:WingRange,signal?:AbortSignal)=>{
  const response=await fetch('/api/desk/profit-period?'+new URLSearchParams(r),{cache:'no-store',signal});
  if(!response.ok)throw Error('기간별 저장 원가를 불러오지 못했습니다.');
  return (await response.json() as ProfitRow).profit?.cost_inputs??null;
 };
 useEffect(()=>{
  if(!range||!row)return;
  const abort=new AbortController();
  readCosts(range,abort.signal).then(setPeriodCosts).catch(()=>{});
  return ()=>abort.abort();
 },[range?.start,range?.end,row?.captured_at]);
 useEffect(()=>{
  if(!pending)return;
  const job=jobs.find(j=>j?.id===pending);
  if(!job)return;
  if(!['complete','failed','partial'].includes(job.state)){
   if(Date.now()-Date.parse(job.created_at)>900000){setPending('');setPeriodMessage('Wing 조회 응답 시간이 지났습니다. 수집 PC 연결을 확인하고 다시 시도해 주세요.');}
   return;
  }
  setPending('');setPeriodMessage(job.message||'Wing 조회 결과를 확인해 주세요.');
 },[jobs,pending]);
 const requestPeriod=async(r:WingRange)=>{
  if(!online){setPeriodMessage('수집 PC 연결 후 Wing에서 조회할 수 있습니다. 이미 확보한 기간은 계속 볼 수 있습니다.');return;}
  setSending(true);setPeriodMessage('');
  try{
   const res=await fetch('/api/desk/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'profit-period',...r})});
   const body=await res.json() as ProfitRow;if(!res.ok||!body.job?.id)throw Error(body.error||'Wing 조회 요청 실패');
   setPending(body.job.id);setPeriodMessage('수집 PC에서 Wing 원본을 확인하고 있습니다.');await onSaved();
  }catch(error){setPeriodMessage(error instanceof Error?error.message:'Wing 조회 요청 실패');}finally{setSending(false);}
 };
 const choose=(v:typeof mode)=>{
  setMode(v);setPeriodMessage('');setDetailsOpen(false);
  if(v==='custom'){
   if(!start&&!end){const initial=range??presets.week;setStart(initial.start);setEnd(initial.end);}
   return;
  }
  const r=wingRange(presets[v].start,presets[v].end);
  if(r&&!exactWingRow(s.finance,r))void requestPeriod(r);
 };
 const periodBusy=sending||!!pending;
 const metric=(key:string)=>onMetric(key,row??undefined,p);
 const graphic=cashGraphic(p);
 const colors=['#496cf2','#4bb9ae','#a0b6e5','#c397df'];
 const shortWon=(v:any)=>v==null?'미확인':Number(v).toLocaleString('ko-KR');
 const pct=(v:any)=>v==null?'미확인':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:1})+'%';
 useEffect(()=>{setCogs(p.cogs==null?'':String(p.cogs));setExtra(p.extra==null?'':String(p.extra));setConfirmed(!!p.confirmed)},[p.basis,p.cogs,p.extra,p.confirmed]);
 const valid=cogs.trim()!==''&&extra.trim()!==''&&Number.isSafeInteger(Number(cogs))&&Number(cogs)>=0&&Number(cogs)<=1e12&&Number.isSafeInteger(Number(extra))&&Math.abs(Number(extra))<=1e12;
 const save=async()=>{if(!valid||!confirmed)return;setBusy(true);setMessage('');try{const response=await fetch('/api/desk/profit-costs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({basis:p.basis,start:p.start,end:p.end,cogs:Number(cogs),extra:Number(extra),confirmed})});const data=await response.json() as ProfitRow;if(!response.ok)throw Error(data.error||'저장하지 못했습니다.');await onSaved();if(range)setPeriodCosts(await readCosts(range));setMessage('기간별 비용을 비공개 웹에 저장했습니다. 다른 PC에서도 같은 계산을 볼 수 있습니다.')}catch(error){setMessage(error instanceof Error?error.message:'비용 저장 실패')}finally{setBusy(false)}};
 const reset=async()=>{setBusy(true);setMessage('');try{const response=await fetch('/api/desk/profit-costs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({basis:p.basis,start:p.start,end:p.end,reset:true})});if(!response.ok)throw Error();await onSaved();if(range)setPeriodCosts(await readCosts(range));setMessage('매출원가와 추가 비용을 미확인 상태로 바꿨습니다.')}catch{setMessage('변경하지 못했습니다. 다시 시도해 주세요.')}finally{setBusy(false)}};
 return <><section className="cash-overview" aria-label="매출과 비용 인포그래픽"><header className="cash-heading"><div><span className="cash-kicker"><span/> FINANCIAL PULSE</span><h2>돈의 흐름, 한눈에.</h2></div><div className="cash-period"><span>윙 수익 기준</span><strong>{p.available?p.start+' ~ '+p.end:range?range.start+' ~ '+range.end:'조회기간 선택'}</strong></div></header>
 {periodControls&&<div className="cash-range"><div className="cash-range-controls"><div className="cash-range-tabs" role="group" aria-label="Wing 수익 조회기간">{([['week','최근 7일'],['last','지난 달'],['month','이번 달'],['custom','직접 지정']] as const).map(([key,label])=><button key={key} type="button" disabled={periodBusy} aria-pressed={mode===key} onClick={()=>choose(key)}>{label}</button>)}</div>{mode==='custom'&&<div className="cash-range-dates"><label>시작일<input type="date" min={WING_MIN} max={end||presets.week.end} value={start} disabled={periodBusy} onChange={e=>{setStart(e.target.value);setPeriodMessage('')}}/></label><label>종료일<input type="date" min={start||WING_MIN} max={presets.week.end} value={end} disabled={periodBusy} onChange={e=>{setEnd(e.target.value);setPeriodMessage('')}}/></label></div>}<button type="button" className="secondary cash-range-query" disabled={!range||periodBusy} onClick={()=>range&&requestPeriod(range)}>{periodBusy?'Wing 조회 중…':p.available?'Wing에서 다시 조회':'Wing에서 조회'}</button></div><p className="cash-range-note">쿠팡 Wing 기준 · 2024년 10월 1일부터 전일까지 · 부가세 포함</p>{periodMessage&&<p className="cash-range-status" role="status">{periodMessage}</p>}</div>}
 {p.available?<><div className="cash-layout"><div className="cash-flow"><div className="cash-numbers"><button className="cash-number income" onClick={()=>metric('finance_revenue')}><span><Wallet size={16}/>{p.other_income?'총매출 + 기타수익':'총매출'}<ArrowUpRight size={14}/></span><strong>{shortWon(p.total_income)}<small>원</small></strong><small>{p.other_income?'판매매출 '+won(p.revenue)+' · 보상 '+won(p.other_income):'상품이 팔린 금액'}</small></button><ArrowRight className="cash-arrow" size={18}/><button className="cash-number expense" onClick={()=>metric('finance_expenses')}><span><ChartNoAxesCombined size={16}/>{p.confirmed?'총비용':'확보된 윙 비용'}<ArrowUpRight size={14}/></span><strong>{shortWon(p.confirmed?p.total_cost:p.wing_cost)}<small>원</small></strong><small>{p.confirmed?'매출원가·추가 비용 반영':'광고 · 물류 · 판매 수수료'}</small></button><ArrowRight className="cash-arrow" size={18}/><button className={'cash-number balance '+((p.confirmed?p.net_profit:p.before_cogs)<0?'negative':'positive')} onClick={()=>setDetailsOpen(true)}><span>{p.confirmed?'입력 기준 순이익':'원가 차감 전'}<ArrowUpRight size={14}/></span><strong>{shortWon(p.confirmed?p.net_profit:p.before_cogs)}<small>원</small></strong><small>{p.confirmed?'최종 마감 미확정':'윙 비용을 뺀 금액 · 순이익 아님'}</small></button></div><div className="cash-comparison"><div className="cash-comparison-title"><span>매출과 윙 비용 비교 <small>매출원가 별도</small></span><strong>{graphic.expense_ratio==null?'비교 미확인':(p.other_income?'총수익':'매출')+' 대비 '+pct(graphic.expense_ratio)}</strong></div><div className="cash-rails" role="img" aria-label={'매출 '+won(p.total_income)+', 윙 비용 '+won(p.wing_cost)+'. 매출원가와 추가 비용은 제외한 비교입니다.'}><span>매출{p.other_income?'·기타수익':''}</span><div><i className="income-rail" style={{width:(graphic.income_width??0)+'%'}}/></div><span>윙 비용</span><div><i className="expense-rail" style={{width:(graphic.cost_width??0)+'%'}}/></div></div></div></div><div className="cash-cost-chart"><div className="cash-donut" role="img" aria-label={graphic.available?'윙 비용 비중: '+graphic.segments.map((part:ProfitRow)=>part.label+' '+pct(part.share*100)).join(', '):'비용 비중을 계산할 자료가 부족합니다.'}><svg viewBox="0 0 144 144" aria-hidden="true"><circle cx="72" cy="72" r="57" className="cash-donut-base"/>{graphic.available&&graphic.segments.map((part:ProfitRow,i:number)=><circle key={part.key} cx="72" cy="72" r="57" pathLength="100" stroke={colors[i%colors.length]} strokeDasharray={(part.share*100)+' '+(100-part.share*100)} strokeDashoffset={-part.offset*100} className="cash-donut-segment"/>)}</svg><div><span>{graphic.available?graphic.segments.reduce((top:ProfitRow,part:ProfitRow)=>part.share>top.share?part:top,graphic.segments[0]).label+" 비중":"윙 비용 구성"}</span><strong>{graphic.available?pct(Math.max(...graphic.segments.map((part:ProfitRow)=>part.share))*100):"미확인"}</strong><small>윙 비용 기준</small></div></div><div className="cash-legend"><span className="cash-legend-title">어디에 쓰였나요?</span>{graphic.segments.map((part:ProfitRow,i:number)=><button key={part.key} onClick={()=>metric('finance_expenses')} title={part.description}><span className="cash-legend-dot" style={{background:colors[i%colors.length]}}/><span>{part.label}</span><strong>{shortWon(part.amount)}<small>원</small></strong><b>{part.share==null?'—':pct(part.share*100)}</b></button>)}</div></div></div><footer className="cash-footer"><div><span className={'cash-net-status '+(p.confirmed?'known':'')}><span/>{p.confirmed?'순이익 · 입력 기준 계산':'순이익 · 원가 입력 필요'}</span><span className="cash-source-clock"><Clock3 size={12}/>{stamp(p.captured_at)}{review?' · 재확인 필요':''}</span></div><button onClick={()=>setDetailsOpen(true)}><SlidersHorizontal size={14}/>{p.confirmed?'비용 입력 확인':'원가·추가 비용 입력'}<ArrowRight size={14}/></button></footer></>:<div className="cash-unavailable"><ChartNoAxesCombined size={27}/><p>{periodControls?(range?'선택한 기간의 검증 원본이 없습니다. Wing에서 조회해 주세요.':'쿠팡 Wing에서 조회 가능한 시작일과 종료일을 선택해 주세요.'):'같은 기간의 매출·비용을 연결하면 흐름이 표시됩니다.'}</p></div>}</section>
 <Dialog.Root open={detailsOpen} onOpenChange={setDetailsOpen}><Dialog.Portal><Dialog.Overlay className="cash-details-overlay"/><Dialog.Content className="cash-details-dialog"><header><div><Dialog.Title>순이익 계산 · 비용 입력</Dialog.Title><Dialog.Description>{p.start} ~ {p.end} · 윙 비용 {won(p.wing_cost)}에 매출원가와 추가 비용을 반영합니다.</Dialog.Description></div><Dialog.Close className="icon-btn" aria-label="비용 입력 닫기"><X size={20}/></Dialog.Close></header><div className="cash-details-note"><Info size={17}/><p>{p.confirmed?'입력 기준의 계산이며 최종 취소·환불·세금·비용 누락 대조 전입니다.':p.missing?.join(' ')} {review?'현재 윙 수익 원본의 기준 시각도 재확인이 필요합니다.':''}</p></div><div className="profit-cost-form"><div className="profit-input-note"><strong>{p.start} ~ {p.end}에 해당하는 비용만 입력하세요.</strong><p>매출원가는 이 기간에 판매한 상품의 원가입니다. 아직 팔리지 않은 재고의 전체 사입금액은 넣지 않습니다. 광고비·판매 수수료·물류비 등 윙 비용에 이미 포함된 금액은 다시 더하지 마세요.</p></div><label>판매한 상품의 매출원가 <span>원</span><input type="number" min="0" max="1000000000000" step="1" value={cogs} onChange={e=>{setCogs(e.target.value);setConfirmed(false)}} placeholder="미입력"/><small>이 기간 판매분의 원가 합계 · 미판매 재고 제외</small></label><label>윙 비용 외 추가 비용 <span>원</span><input type="number" min="-1000000000000" max="1000000000000" step="1" value={extra} onChange={e=>{setExtra(e.target.value);setConfirmed(false)}} placeholder="미입력"/><small>포장·외부 배송·인건비 등 · 환급·차감은 음수 · 없으면 직접 0 입력</small></label><label className="profit-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>동일 기간의 매출원가와 추가 비용이며, 윙 비용과 중복되지 않는지 확인했습니다.</label><div className="profit-save"><button className="primary" disabled={!valid||!confirmed||busy} onClick={save}><Check size={15}/>{busy?'저장 중':'비용 저장 · 순이익 계산'}</button><small>원본이나 조회기간이 바뀌면 비용을 다시 확인하도록 표시합니다.</small>{p.confirmed&&<button className="text-link" disabled={busy} onClick={reset}>비용을 미확인으로 되돌리기</button>}</div>{message&&<p className="profit-save-message" role="status">{message}</p>}</div></Dialog.Content></Dialog.Portal></Dialog.Root></>
}
