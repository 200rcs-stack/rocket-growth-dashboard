"use client";
import ProductName from './product-name';
import {useEffect,useMemo,useRef,useState} from 'react';
import {Dialog} from 'radix-ui';
import {ArrowRight,Check,Download,FileSpreadsheet,Info,Search,Wallet,X} from 'lucide-react';
import {costAnalytics,costKey} from '../lib/product-costs';
import {costImport,parseCsv} from '../lib/cost-import';
type Row=Record<string,any>;
const number=(v:any)=>v==null?'계산 대기':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2});
const won=(v:any)=>v==null?'계산 대기':number(v)+'원';
function download(text:string,name:string,type='text/csv;charset=utf-8'){
 const url=URL.createObjectURL(new Blob([text],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const csvCell=(v:any)=>'"'+String(v??'').replace(/^[\s\u0000-\u001f]*[=+@-]/,"'$&").replaceAll('"','""')+'"';
export default function ProductCostDesk({snapshot:s,open,onOpenChange,onSaved}:{snapshot:Row;open:boolean;onOpenChange:(v:boolean)=>void;onSaved:()=>Promise<void>}){
 const [draft,setDraft]=useState<Record<string,string>>({}),[confirmed,setConfirmed]=useState(false),[query,setQuery]=useState(''),[view,setView]=useState('input'),[message,setMessage]=useState(''),[errors,setErrors]=useState<string[]>([]),[busy,setBusy]=useState(false),[base,setBase]=useState<Row|null>(null);
 const upload=useRef<HTMLInputElement>(null),dialog=useRef<HTMLDivElement>(null),inventory:Row[]=s.inventory||[];
 const source=s.sources?.find((r:Row)=>r.id==='inventory');
 useEffect(()=>{dialog.current?.scrollTo({top:0})},[view,open]);
 useEffect(()=>{if(open){setErrors([]);setMessage('')}},[open]);
 const working=inventory.map(r=>Object.hasOwn(draft,costKey(r))?{...r,unit_cost:draft[costKey(r)]===''?null:Number(draft[costKey(r)]),cost_sales_confirmed:confirmed}:r);
 const analysis=useMemo(()=>costAnalytics({...s,inventory:working}),[s,draft,confirmed]);
 const shown=working.filter(r=>(r.product_name+' '+r.option_name+' '+r.option_id).toLowerCase().includes(query.toLowerCase())).sort((a,b)=>(b.rev_30d??-Infinity)-(a.rev_30d??-Infinity));
 const changed=Object.keys(draft).length;
 const edit=(key:string,value:string)=>{if(!base)setBase(s.product_cost_master);setDraft(old=>({...old,[key]:value}));setConfirmed(false);setMessage('');setErrors([])};
 const template=()=>{const rows=[['옵션ID','등급','상품명','옵션명','매입원가(원)'],...inventory.map(r=>[r.option_id,r.grade,r.product_name,r.option_name,r.unit_cost])];download('\uFEFF'+rows.map(r=>r.map(csvCell).join(',')).join('\r\n'),'RocketDesk_매입원가_입력양식.csv');};
 const importFile=async(file?:File)=>{
  if(!file)return;setErrors([]);setMessage('');setBusy(true);
  try{
   if(file.size>5_000_000)throw Error('파일은 5MB 이하로 올려 주세요.');
   let table:unknown[][];
   if(/\.xlsx$/i.test(file.name)){const {default:read}=await import('read-excel-file');table=await read(file);}
   else if(/\.csv$/i.test(file.name)){const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());table=parseCsv(text);}
   else throw Error('.xlsx 또는 UTF-8 CSV 파일을 선택해 주세요. 암호·매크로 파일은 지원하지 않습니다.');
   const parsed=costImport(table,inventory);if(parsed.errors.length){setErrors(parsed.errors);return;}
   setBase(s.product_cost_master);setDraft(Object.fromEntries(parsed.entries.map(r=>[costKey(r),String(r.unit_cost)])));setConfirmed(false);setView('input');setMessage(`${parsed.entries.length}개 항목을 미리 불러왔습니다. 대조 후 저장해야 반영됩니다. 빈칸은 기존 원가를 지우지 않습니다.`);
  }catch(error){setErrors([error instanceof Error?error.message:'파일을 읽지 못했습니다. 양식과 파일 형식을 확인해 주세요.'])}finally{setBusy(false);if(upload.current)upload.current.value='';}
 };
 const save=async()=>{
  if(!changed||!confirmed||busy)return;setBusy(true);setErrors([]);setMessage('');
  try{
   const entries=inventory.filter(r=>Object.hasOwn(draft,costKey(r))).map(r=>({option_id:String(r.option_id),grade:String(r.grade??''),unit_cost:draft[costKey(r)]===''?null:Number(draft[costKey(r)])}));
   const response=await fetch('/api/desk/product-costs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entries,revision:base?.revision??s.product_cost_master.revision,basis:base?.basis??s.product_cost_master.basis,confirmed})});
   const data=await response.json() as Row;if(!response.ok)throw Error(data.error||'저장하지 못했습니다.');await onSaved();setDraft({});setBase(null);setConfirmed(false);setView('analysis');setMessage('원가를 비공개 웹에 저장했습니다. 다른 PC와 AI 대화에도 같은 원가가 반영됩니다.');
  }catch(error){setErrors([error instanceof Error?error.message:'저장 실패'])}finally{setBusy(false)}
 };
 const renew=()=>{setBase(s.product_cost_master);setDraft(Object.fromEntries(inventory.filter(r=>r.unit_cost!=null).map(r=>[costKey(r),String(r.unit_cost)])));setConfirmed(false);setView('input');setMessage('기존 단위원가를 현재 보고서에 다시 적용할 준비를 했습니다. 판매분 전체에 유효한 원가인지 확인 후 저장하세요.');};
 const exportAnalysis=()=>{const columns=[['option_id','옵션ID'],['grade','등급'],['product_name','상품명'],['unit_cost','입력단위원가'],['qty_30d','보고서30일판매수량'],['rev_30d','보고서30일판매금액'],['report_cogs','적용매출원가'],['gross_difference','원가차감금액_기타비용전'],['gross_margin','원가차감률_퍼센트'],['stock_cost','판매가능재고원가'],['long_stock_cost','장기보관재고원가'],['restock_cost','권장입고원가'],['cost_sales_confirmed','현재보고서원가적용확인']];download('\uFEFF'+[columns.map(x=>csvCell(x[1])).join(','),...analysis.rows.map((r:Row)=>columns.map(x=>csvCell(r[x[0]])).join(','))].join('\r\n'),'RocketDesk_원가기준_분석.csv');};
 const metrics=[
  ['판매분 매출원가',analysis.cogs,'단위원가 × 보고서 판매수량'],['원가 차감 금액',analysis.gross,'판매금액 − 판매분 원가 · 기타 비용 전'],
  ['원가 차감률',analysis.margin==null?null:number(analysis.margin)+'%','원가 차감 금액 ÷ 같은 항목 판매금액'],['원가 대비 차액률',analysis.markup==null?null:number(analysis.markup)+'%','원가 차감 금액 ÷ 판매분 원가'],
  ['판매가능재고 원가',analysis.stock_cost,'단위원가 × 판매가능재고'],['입고 예정 원가',analysis.inbound_cost,'단위원가 × 입고 예정 수량'],
  ['61일 이상 보관 원가',analysis.long_stock_cost,'단위원가 × 장기보관 수량'],['권장 입고 필요금액',analysis.restock_cost,'권장 입고 수량 × 단위원가 · 실제 발주 전'],
  ['원가만 반영 ROAS 기준',analysis.cost_only_roas==null?null:number(analysis.cost_only_roas)+'%','100 ÷ 원가 차감률 · 광고 외 비용 제외 하한'],
 ];
 return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="cash-details-overlay"/><Dialog.Content ref={dialog} className="cost-desk-dialog"><header><div><span className="eyebrow">COST INTELLIGENCE</span><Dialog.Title>매입원가 입력 · 수익성 분석</Dialog.Title><Dialog.Description>상품·옵션·등급별 개당 원가를 입력하세요. 직접 입력과 엑셀 업로드를 모두 지원합니다.</Dialog.Description></div><Dialog.Close className="icon-btn" aria-label="매입원가 관리 닫기"><X size={22}/></Dialog.Close></header>
 <p className="cost-help"><b>기준 원본:</b> {source?.time?new Date(source.time).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' KST':'시각 미확인'} · {source?.quality?.review_required?'최신 원본 재확인 필요':'수집 자료 기준'} · 원가는 사용자가 확인해 입력한 값입니다.</p>
 <div className="cost-desk-summary"><div><Wallet size={22}/><span>원가 입력 <strong>{analysis.entered} / {analysis.total}</strong>개 항목</span></div><div><span>판매분 계산 가능 <strong>{analysis.matched} / {analysis.total}</strong>개 항목</span><small>{analysis.full?'전체 보고서 범위 계산 가능':'원가 적용 확인·판매수량이 없는 항목 제외'}</small></div></div>
 <div className="cost-desk-tabs"><button aria-pressed={view==='input'} onClick={()=>setView('input')}>원가 입력 · 엑셀 첨부</button><button aria-pressed={view==='analysis'} onClick={()=>setView('analysis')}>원가 기반 지표 {changed?'· 미리보기':''}</button></div>
 {message&&<p className="cost-status" role="status">{message}</p>}{errors.length>0&&<div className="cost-errors" role="alert"><strong>저장하지 않았습니다. 다음 내용을 확인하세요.</strong>{errors.slice(0,10).map((error,i)=><p key={i}>{error}</p>)}{errors.length>10&&<p>외 {errors.length-10}개 오류</p>}</div>}
 {view==='input'?<><div className="cost-toolbar"><button className="secondary" onClick={template}><Download size={16}/>엑셀용 양식 받기</button><button className="secondary" disabled={busy} onClick={()=>upload.current?.click()}><FileSpreadsheet size={16}/>엑셀·CSV 첨부</button><input ref={upload} type="file" accept=".xlsx,.csv" aria-label="매입원가 엑셀 첨부" className="sr-only" onChange={e=>importFile(e.target.files?.[0])}/><button className="text-link" onClick={renew}>저장된 원가 재확인</button><label className="search"><Search size={16}/><input aria-label="원가 상품 검색" placeholder="상품명·옵션ID 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
 <details className="cost-input-guide"><summary>입력 기준 · 엑셀 작성 방법</summary><p className="product-group-note">같은 상품명은 같은 색·상품 표시로 묶었습니다. 옵션·등급별 원가는 각각 입력합니다.</p><p className="cost-help">매입원가는 <b>개당 원가(원)</b>입니다. 운송·관세 등을 포함할지는 동일 기준으로 입력하세요. 빈칸은 미입력, 0은 원가 0원입니다. 양식의 옵션ID·등급은 바꾸지 마세요. XLSX는 첫 시트, CSV는 UTF-8로 읽으며 파일은 이 브라우저에서 분석 후 선택된 원가만 저장합니다.</p></details>
 <div className="cost-table-scroll"><table><thead><tr><th>상품 / 옵션 / 등급</th><th>개당 매입원가(원)</th><th>30일 판매수량</th><th>30일 판매금액</th><th>판매가능재고</th></tr></thead><tbody>{shown.map(r=>{const key=costKey(r);return <tr key={key}><td><ProductName row={r}/><small>{r.option_name} · {r.grade} · {r.option_id}</small><small>{r.cost_updated_at?'저장 '+new Date(r.cost_updated_at).toLocaleString('ko-KR'):r.cost_origin}</small></td><td><input type="number" min="0" max="1000000000" step="0.01" aria-label={r.option_id+' '+r.grade+' 매입원가'} value={Object.hasOwn(draft,key)?draft[key]:r.unit_cost??''} placeholder="미입력" onChange={e=>edit(key,e.target.value)}/>{Object.hasOwn(draft,key)&&<small>저장 전 변경</small>}</td><td>{r.qty_30d==null?'미확인':number(r.qty_30d)+'개'}</td><td>{won(r.rev_30d)}</td><td>{r.stock_available==null?'미확인':number(r.stock_available)+'개'}</td></tr>})}</tbody></table>{!shown.length&&<p className="empty">검색 조건에 맞는 상품이 없습니다.</p>}</div>
 <footer className="cost-save"><label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>변경한 단위원가가 현재 보고서의 지난 30일 판매분 전체에 동일하게 적용됩니다. 기간 중 원가가 달랐다면 판매분 가중평균 원가인지 확인했습니다.</label><div><span>{changed}개 항목 변경 · 저장 전 지표는 미리보기입니다.</span><button className="primary" disabled={!changed||!confirmed||busy||!!errors.length} onClick={save}><Check size={16}/>{busy?'처리 중':'원가 저장 · 지표 계산'}</button>{changed>0&&<button className="text-link" onClick={()=>{setDraft({});setBase(null);setConfirmed(false);setErrors([]);setMessage('변경 전 값으로 돌아왔습니다.')}}>변경 취소</button>}</div><small>새 보고서가 들어오면 판매분 원가 적용을 다시 확인합니다. 이전 저장 이력은 보관합니다.</small></footer></>:<><div className="cost-scope"><Info size={18}/><p>{analysis.note}<br/><b>판매분 지표: {analysis.matched}/{analysis.total}개 항목 · 재고 원가: {analysis.stock_covered}/{analysis.total}개 항목. 부분 집계를 전체 금액으로 해석하지 마세요.</b></p></div><div className="cost-kpi-grid">{metrics.map(([name,value,formula])=><article key={String(name)}><span>{name}</span><strong>{value==null?'계산 대기':typeof value==='number'?won(value):value}</strong><small>{formula}</small></article>)}</div><div className="cost-blocked"><strong>순이익·정확한 광고 손익분기점은 추가 대조가 필요합니다.</strong><p>상품별 실제 수수료·물류비·광고비·환불·추가 비용이 동일 기간으로 연결되어야 합니다. 원가만 반영한 ROAS는 다른 비용을 제외한 하한이며 광고 집행 기준으로 단독 사용하지 마세요. 윙 기간 순이익은 메인의 ‘원가·추가 비용 입력’에서 같은 기간 판매분 총원가를 별도로 확인합니다.</p></div><div className="cost-analysis-heading"><h3>상품별 원가 · 수익성 · 자금 지표</h3><button className="secondary" onClick={exportAnalysis}><Download size={16}/>분석 CSV 저장</button></div><div className="cost-table-scroll"><table><thead><tr><th>상품 / 옵션</th><th>매출원가</th><th>원가 차감 금액</th><th>원가 차감률</th><th>평균 판매단가</th><th>재고 원가</th><th>입고 필요금액</th></tr></thead><tbody>{[...analysis.rows].sort((a:Row,b:Row)=>(b.gross_difference??-Infinity)-(a.gross_difference??-Infinity)).map((r:Row)=><tr key={costKey(r)}><td><ProductName row={r}/><small>{r.option_name} · {r.grade}</small></td><td>{won(r.report_cogs)}</td><td className={r.gross_difference<0?'cost-negative':''}>{won(r.gross_difference)}</td><td>{r.gross_margin==null?'계산 대기':number(r.gross_margin)+'%'}</td><td>{won(r.average_price)}</td><td>{won(r.stock_cost)}</td><td>{won(r.restock_cost)}</td></tr>)}</tbody></table></div><button className="text-link" onClick={()=>setView('input')}>원가 채우기 <ArrowRight size={16}/></button></>}
 </Dialog.Content></Dialog.Portal></Dialog.Root>
}
