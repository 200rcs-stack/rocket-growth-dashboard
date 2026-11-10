"use client";
import {useEffect,useState} from 'react';
import {readableTerms} from '../lib/display-terms';
import {BookOpen,Check,ChevronRight,ShieldCheck,TriangleAlert} from 'lucide-react';

export default function Manual({manual,sourceButton}:{manual:any;sourceButton:(ids:string[])=>React.ReactNode}){
 const [active,setActive]=useState('data'),[checks,setChecks]=useState<Record<string,boolean>>({});
 const key='rocketdesk-manual-'+(manual?.version||'v1');
 useEffect(()=>{try{setChecks(JSON.parse(localStorage.getItem(key)||'{}'))}catch{setChecks({})}},[key]);
 const toggle=(id:string)=>setChecks(old=>{const next={...old,[id]:!old[id]};try{localStorage.setItem(key,JSON.stringify(next))}catch{}return next});
 if(!manual)return <div className="empty">수집 PC에서 운영 매뉴얼을 동기화하면 표시됩니다.</div>;
 const section=manual.sections.find((s:any)=>s.id===active)||manual.sections[0];
 const count=section.steps.filter((_:any,i:number)=>checks[section.id+'-'+i]).length;
 return <div className="manual-layout"><section className="panel manual-index"><div className="panel-heading"><div><span className="eyebrow">운영 기준서</span><h2>순서대로 점검하세요</h2></div><BookOpen size={22}/></div><label className="manual-topic-select">점검할 주제<select aria-label="매뉴얼 주제 선택" value={section.id} onChange={e=>setActive(e.target.value)}>{manual.sections.map((s:any)=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label><nav aria-label="매뉴얼 주제">{manual.sections.map((s:any,i:number)=><button key={s.id} aria-current={section.id===s.id?'step':undefined} className={section.id===s.id?'active':''} onClick={()=>setActive(s.id)}><span>{String(i+1).padStart(2,'0')}</span><strong>{s.title}</strong><ChevronRight size={16}/></button>)}</nav><p className="manual-version">검토 기준 {manual.version}<br/>체크 기록은 이 브라우저에 저장됩니다.</p></section>
 <article className="panel manual-detail"><div className="panel-heading"><div><span className="eyebrow">{section.when}</span><h2>{section.title}</h2></div><span className="badge">{count} / {section.steps.length} 확인</span></div>
 <div className="manual-body"><div className="manual-completion"><Check size={20}/><div><strong>점검 완료 기준</strong><p>{section.completion}</p></div></div>{section.source_review_required&&<div className="notice warning"><TriangleAlert size={20}/><div><strong>원본 재확인부터 시작하세요</strong><p>이 절차에 쓰는 자료에 갱신 실패, 기준 시각 경과 또는 미수집 항목이 있습니다. 체크를 마쳐도 자료의 누락이 해결되는 것은 아닙니다.</p></div></div>}
 <div className="manual-checks">{section.steps.map((text:string,i:number)=><label key={i} className={checks[section.id+'-'+i]?'checked':''}><input type="checkbox" checked={!!checks[section.id+'-'+i]} onChange={()=>toggle(section.id+'-'+i)}/><span className="check-number">{i+1}</span><span>{readableTerms(text)}</span></label>)}</div>
 <div className="manual-stop"><h3><ShieldCheck size={20}/>이럴 때는 판단을 멈추세요</h3><ul>{section.stop_conditions.map((text:string)=><li key={text}>{text}</li>)}</ul></div>
 {sourceButton(section.source_ids)}<p className="manual-scope">{manual.scope}</p>
 </div></article></div>
}
