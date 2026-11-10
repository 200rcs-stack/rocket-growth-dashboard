"use client";
import ProductName from './product-name';
import {useMemo,useRef,useState} from 'react';
import {Dialog} from 'radix-ui';
import {ArrowDownToLine,ArrowDownUp,ArrowRight,ChevronLeft,ChevronRight,Database,FileSpreadsheet,Info,Search,ChevronDown,ShieldCheck,X} from 'lucide-react';
import {metricData,sortedMetricRows,type DataRow,type MetricColumn} from '../lib/metric-data';
const number=(v:any)=>v==null?'미확인':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:2});
const stamp=(v?:string)=>v?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})+' KST':'미수집';
function formatted(value:any,column:MetricColumn){
  if(value==null)return '미확인';
  if(column.format==='date')return String(value).slice(0,10);
  if(column.format)return number(value)+({money:'원',days:'일',percent:'%',number:''}[column.format]);
  return String(value);
}
export default function MetricExplorer({snapshot,metricKey,initialQuery="",onClose,onProduct,onNavigate,onExport}:{snapshot:DataRow;metricKey:string;initialQuery?:string;onClose:()=>void;onProduct:(row:DataRow)=>void;onNavigate:(tab:string)=>void;onExport:(rows:DataRow[],name:string)=>void}){
  const metric=useMemo(()=>metricData(snapshot,metricKey),[snapshot,metricKey]);
  const [query,setQuery]=useState(initialQuery),[sort,setSort]=useState(metric.sortKey),[ascending,setAscending]=useState(!!metric.ascending),[page,setPage]=useState(0);
  const opener=useRef(typeof document==='undefined'?null:document.activeElement as HTMLElement|null);
  const source=snapshot.sources.find((s:DataRow)=>s.id===metric.sourceId);
  const rows=useMemo(()=>sortedMetricRows(metric,query,sort,ascending),[metric,query,sort,ascending]);
  const pages=Math.max(1,Math.ceil(rows.length/20)),safePage=Math.min(page,pages-1),visible=rows.slice(safePage*20,(safePage+1)*20);
  const kind=({inventory:'inventory',returns:'returns',settlement:'settlement_detail',ad_detail:'ad_performance'} as DataRow)[metric.sourceId];
  const originals=(snapshot.files||[]).filter((f:DataRow)=>kind&&f.kind===kind&&f.active);
  const target=metric.sourceId==='returns'?'returns':['finance','ads'].includes(metric.sourceId)?'finance':'inventory';
  return <Dialog.Root open onOpenChange={open=>{if(!open)onClose()}}><Dialog.Portal>
    <Dialog.Overlay className="explorer-overlay"/>
    <Dialog.Content className="metric-explorer panel" onCloseAutoFocus={e=>{e.preventDefault();opener.current?.focus()}}>
      <header className="explorer-header"><div><span className="eyebrow">숫자에서 실제 내역까지</span><Dialog.Title>{metric.title}</Dialog.Title></div><Dialog.Close className="icon-btn" aria-label="지표 상세 닫기"><X size={23}/></Dialog.Close></header>
      <div className="explorer-body"><div className="explorer-summary"><div><span>선택한 지표</span><strong>{number(metric.value)}{metric.value!=null&&<small>{metric.unit}</small>}</strong><p>{metric.rows.length.toLocaleString('ko-KR')}개 상세 항목 · {metric.sourceId==='api_inventory'?'옵션 기준':metric.sourceId==='returns'?'반품 접수 기준':'원본 범위 기준'}</p></div><div className="explorer-source"><span className={'badge '+(source?.quality?.review_required?'amber':'muted')}>{source?.quality?.review_required?'자료 재확인 필요':source?.status||'미수집'}</span><strong><Database size={15}/>{source?.name}</strong><span>자료 기준 {stamp(source?.time)}</span>{source?.quality?.review_required&&<span>{source?.status}</span>}</div></div>
      <Dialog.Description className="explorer-explanation">{metric.explanation}</Dialog.Description>
      <details className="explorer-formula"><summary><Info size={19}/><strong>계산 방식과 주의사항</strong><ChevronDown size={17}/></summary><div><p>{metric.formula}</p><small>{metric.caution}</small></div></details>
      <section className="explorer-list"><div className="explorer-list-heading"><div><h3>이 숫자를 구성하는 내역</h3><p>검색은 목록에만 적용됩니다. 열 제목을 누르면 정렬하고, 표를 좌우로 움직이면 나머지 열을 볼 수 있어요.</p></div><button className="secondary" disabled={!rows.length} onClick={()=>onExport(rows.map(row=>Object.fromEntries(metric.columns.map(c=>[c.label,row[c.key]]))),metric.title+'_상세')}><ArrowDownToLine size={16}/>검색 결과 CSV</button></div>
      <div className="explorer-toolbar"><label className="search"><Search size={17}/><input aria-label="상세 내역 검색" placeholder="상품명 · 옵션 ID · 상태 검색" value={query} onChange={e=>{setQuery(e.target.value);setPage(0)}}/></label><span>{rows.length.toLocaleString('ko-KR')}개 / 전체 {metric.rows.length.toLocaleString('ko-KR')}개</span>{query&&<button className="text-link" onClick={()=>{setQuery('');setPage(0)}}>검색 초기화</button>}</div>
      <div className="table-scroll"><table><thead><tr>{metric.columns.map(c=><th key={c.key} aria-sort={sort===c.key?(ascending?'ascending':'descending'):'none'}><button onClick={()=>{setSort(c.key);setAscending(sort===c.key?!ascending:!c.format);setPage(0)}}>{c.label}<ArrowDownUp size={13}/></button></th>)}</tr></thead><tbody>{visible.map((row,index)=><tr key={safePage*20+index}>{metric.columns.map(c=><td key={c.key}>{c.key==='product_name'&&metric.sourceId==='inventory'?<button className="product-link" onClick={()=>onProduct(row)}><ProductName row={row}/><small>상품의 전체 지표 보기 <ArrowRight size={12}/></small></button>:c.key==='product_name'?<ProductName row={row}/>:formatted(row[c.key],c)}</td>)}</tr>)}</tbody></table>{!rows.length&&<div className="empty"><Search size={27}/><p>{query?'검색 조건에 맞는 내역이 없습니다.':'해당 조건의 상세 내역이 없습니다.'}</p><small>내역 없음과 자료 미수집은 다릅니다. 위 수집 상태를 확인하세요.</small></div>}</div>
      <div className="explorer-pagination"><span>{rows.length?`${safePage*20+1}–${Math.min((safePage+1)*20,rows.length)}`:'0'} / {rows.length}개</span><div><button className="secondary" aria-label="이전 상세 페이지" disabled={safePage===0} onClick={()=>setPage(safePage-1)}><ChevronLeft size={16}/></button><span>{safePage+1} / {pages} 페이지</span><button className="secondary" aria-label="다음 상세 페이지" disabled={safePage>=pages-1} onClick={()=>setPage(safePage+1)}><ChevronRight size={16}/></button></div></div></section>
      <section className="explorer-originals"><h3><FileSpreadsheet size={19}/>근거 원본</h3>{originals.length?originals.map((f:DataRow)=><a key={f.id} className="file-link" href={'/api/desk/file/'+f.id}><FileSpreadsheet size={17}/><span>{f.name}<small>원본 엑셀 · {stamp(f.time)}</small></span><ArrowDownToLine size={17}/></a>):<p>{metric.sourceId.startsWith('api_')?'공식 API 조회 자료입니다. 위 CSV로 현재 조회 내역을 저장할 수 있습니다.':'화면에서 수집한 요약 자료입니다. 대응하는 원본 엑셀은 자료실의 기간과 범위를 확인하세요.'}</p>}<small><ShieldCheck size={14}/>웹 상세에는 고객·주문 식별정보를 포함하지 않습니다. 내려받는 원본 파일은 공유 전 확인하세요.</small></section>
      </div><footer className="explorer-footer"><button className="secondary" onClick={()=>onNavigate('sources')}>자료실에서 출처 확인</button><button className="primary" onClick={()=>onNavigate(target)}>관련 메뉴 전체 보기 <ArrowRight size={17}/></button></footer>
    </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
