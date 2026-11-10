'use client';
import {useState} from 'react';

export type ImportMemo={id:string;name:string;quantity:number;unit_cny:number;tax_krw:number;freight_cny:number;freight_basis:'unknown'|'lot'|'unit';approximate_freight:boolean;exchange_rate:number|null;updated_at?:string};
const blank={id:'',name:'',quantity:'',unit_cny:'',tax_krw:'',freight_cny:'',freight_basis:'unknown',approximate_freight:false,exchange_rate:''};
const fields=[['unit_cny','매입 단가 (위안/개)','any',0],['quantity','수입 수량 (개)','1',1],['tax_krw','관세·수입 부가세 합계 (원)','1',0],['freight_cny','중국 물류비 (위안)','any',0],['exchange_rate','적용 환율 (원/위안, 선택)','any',0.0001]] as const;
const basis={unknown:'미확인',lot:'수입 건 전체',unit:'개당'};
export default function OperationMemory({records,loading,onChange,onAsk}:{records:ImportMemo[];loading:boolean;onChange:(r:ImportMemo|null,id:string)=>void;onAsk:(q:string)=>void}){
  const [draft,setDraft]=useState(blank),[busy,setBusy]=useState(false),[status,setStatus]=useState(''),[error,setError]=useState(false),[removing,setRemoving]=useState(false);
  const edit=(r:ImportMemo)=>{setDraft({...r,quantity:String(r.quantity),unit_cny:String(r.unit_cny),tax_krw:String(r.tax_krw),freight_cny:String(r.freight_cny),exchange_rate:r.exchange_rate==null?'':String(r.exchange_rate)});setStatus('');setRemoving(false)};
  const write=async(remove=false)=>{
    const id=draft.id||crypto.randomUUID();setBusy(true);setError(false);setStatus('');
    try{
      const body=remove?{id,remove:true}:{...draft,id,quantity:Number(draft.quantity),unit_cny:Number(draft.unit_cny),tax_krw:Number(draft.tax_krw),freight_cny:Number(draft.freight_cny),exchange_rate:draft.exchange_rate===''?null:Number(draft.exchange_rate)};
      const res=await fetch('/api/desk/chat/memory',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await res.json() as {record?:ImportMemo;error?:string};if(!res.ok||(!remove&&!data.record))throw Error(data.error||'저장하지 못했습니다.');
      onChange(data.record??null,id);setDraft(blank);setRemoving(false);setStatus(remove?'운영 메모를 삭제했습니다. 기존 대화 내역은 유지됩니다.':'저장했습니다. 이후 질문에서도 이 메모를 읽습니다.');
    }catch(e){setError(true);setStatus(e instanceof Error?e.message:'저장하지 못했습니다.');}finally{setBusy(false)}
  };
  return <section className="chat-memory" aria-label="운영 메모">
    <h3>AI가 다음에도 기억할 수입 원가</h3><p>수입 건별로 저장해 두면 같은 계정의 다른 PC에서도 AI가 읽습니다. 쿠팡 상품 원가와 손익표는 바뀌지 않습니다.</p>
    {loading&&<p>저장된 메모를 확인하고 있어요.</p>}
    <div className="chat-memory-list">{records.map(r=><article key={r.id}><div><strong>{r.name}</strong><small>{r.quantity.toLocaleString()}개 · {r.unit_cny.toLocaleString()}위안/개 · 중국 물류비 {r.freight_cny.toLocaleString()}위안{r.approximate_freight?'(추정)':''}, 기준 {basis[r.freight_basis]}</small></div><button type="button" className="secondary" onClick={()=>onAsk(`${r.name} 수입 원가 계산해줘`)}>질문 준비</button><button type="button" className="secondary" aria-label={`${r.name} 메모 수정`} onClick={()=>edit(r)} disabled={busy}>수정</button></article>)}</div>
    <form className="chat-memory-form" onSubmit={e=>{e.preventDefault();void write()}}>
      <h4>{draft.id?'수입 메모 수정':'새 수입 메모'}</h4>
      <label className="chat-memory-wide">상품명 또는 수입 건 이름<input required maxLength={100} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})} placeholder="예: 캠핑 텐트 · 11월 수입분"/></label>
      {fields.map(([key,label,step,min])=><label key={key}>{label}<input required={key!=='exchange_rate'} type="number" inputMode={step==='1'?'numeric':'decimal'} min={min} step={step} value={draft[key]} onChange={e=>setDraft({...draft,[key]:e.target.value})}/></label>)}
      <label>중국 물류비 기준<select value={draft.freight_basis} onChange={e=>setDraft({...draft,freight_basis:e.target.value})}><option value="unknown">미확인 · 두 경우 계산</option><option value="lot">수입 건 전체</option><option value="unit">개당</option></select></label>
      <label className="chat-memory-check"><input type="checkbox" checked={draft.approximate_freight} onChange={e=>setDraft({...draft,approximate_freight:e.target.checked})}/>중국 물류비가 추정값입니다</label>
      <div className="chat-memory-actions chat-memory-wide"><button className="primary" disabled={busy}>{busy?'처리 중…':'메모 저장'}</button>{draft.id&&<><button type="button" className="secondary" disabled={busy} onClick={()=>{setDraft(blank);setRemoving(false)}}>수정 취소</button><button type="button" className="secondary" disabled={busy} onClick={()=>{if(removing)void write(true);else setRemoving(true)}}>{removing?'이 메모 삭제 확인':'메모 삭제'}</button></>}</div>
    </form>
    {status&&<p role={error?'alert':'status'}>{status}</p>}
  </section>;
}
