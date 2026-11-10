"use client";
import {useEffect,useState} from 'react';
import {Clock3,RefreshCw,ChevronDown,Info,Zap,PackageCheck,ShieldCheck,Sparkles} from 'lucide-react';
type Row=Record<string,any>;
export default function RefreshControls({busy,running,online,job,onRefresh}:{busy:boolean;running:boolean;online:boolean;job?:Row;onRefresh:(mode:string)=>void}){
 const [now,setNow]=useState(Date.now());useEffect(()=>{if(!running)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[running]);
 const elapsed=running?Math.max(0,Math.floor((now-Date.parse(job?.started_at||job?.created_at||''))/1000)):null;
 const finished=job?.duration_seconds;
 return <div className="refresh-controls">
  <div className="refresh-buttons">
   <button className="primary" disabled={busy||running||!online} onClick={()=>onRefresh('full')}><RefreshCw size={16} className={busy||running?'spin':''}/>{running?'자료 갱신 진행 중':'전체 자료 새로고침'}</button>
   <button className="secondary" disabled={busy||running||!online} onClick={()=>onRefresh('quick')}><Zap size={15}/>API만 빠르게 갱신</button>
  </div>
  <div className="refresh-estimate"><Clock3 size={13}/>{running&&elapsed!==null?`요청 후 ${Math.floor(elapsed/60)}분 ${elapsed%60}초 경과`:'⚡ API 2~10초(수시) · 📦 전체 20~45초(하루 1~2회)'}</div>
  <details className="refresh-help">
   <summary>무엇을 갱신하고, 얼마나 자주 누를까요? <ChevronDown size={13}/></summary>
   <div className="refresh-help-popover">
    <div className="refresh-help-head">
     <strong>갱신 방식 비교 · 수집 데이터 및 정확도 안내</strong>
     <span>업무 상황에 맞춰 가장 빠른 버튼을 선택하세요</span>
    </div>
    <div className="refresh-help-grid">
     <article className="refresh-card quick">
      <div className="refresh-card-top">
       <span className="refresh-tag blue"><Zap size={13}/> API만 빠르게 갱신</span>
       <small>수시 권장 · 약 2~10초</small>
      </div>
      <p className="refresh-card-desc">쿠팡 공식 Open API 서버와 직접 통신해 <b>로그인 없이 24시간</b> 즉시 가져옵니다.</p>
      <div className="refresh-card-box">
       <strong>📥 가져오는 데이터 (4종)</strong>
       <ul>
        <li><b>실시간 판매가능재고</b> (단품·묶음옵션 자동 연동)</li>
        <li><b>최근 30일 주문 내역</b> (일자·옵션별 수량·주문금액)</li>
        <li><b>옵션별 실시간 판매가</b> 및 묶음 구성 수량</li>
        <li><b>등록 상품·옵션 목록</b> (전체 옵션 ID)</li>
       </ul>
      </div>
      <div className="refresh-accuracy">
       <ShieldCheck size={14}/>
       <div>
        <strong>정확도 100% (실시간 쿠팡 서버 원장)</strong>
        <span>현재 고객에게 노출되는 재고·가격과 100% 일치합니다. (주문은 쿠팡 정책상 ‘출고 완료’ 기준 집계)</span>
       </div>
      </div>
     </article>
     <article className="refresh-card full">
      <div className="refresh-card-top">
       <span className="refresh-tag deep"><PackageCheck size={13}/> 전체 자료 새로고침</span>
       <small>하루 1~2회 · 약 20~45초</small>
      </div>
      <p className="refresh-card-desc"><b>API 빠른 갱신 전체</b>에 더해, 쿠팡윙 화면·엑셀 전용 데이터 5종을 함께 수집합니다.</p>
      <div className="refresh-card-box">
       <strong>📥 추가로 가져오는 쿠팡윙 데이터 (+5종)</strong>
       <ul>
        <li><b>Wing 재고 엑셀</b>: 입고 예정 수량, 권장 입고량·권장일, 61~181일+ 장기보관 수량·보관비</li>
        <li><b>Wing 수익 현황</b>: 총매출, 판매수수료, 풀필먼트 물류비, 광고비 차감, 윙 표시 이익</li>
        <li><b>광고센터 & 청구</b>: 집행 광고비, 전환매출, ROAS(%), 월별 청구액</li>
        <li><b>반품 & 손실보상</b>: 반품 접수·사유, 90일+ 장기 미회수, 월별 반품률, 창고 분실·파손 보상액</li>
       </ul>
      </div>
      <div className="refresh-accuracy">
       <ShieldCheck size={14}/>
       <div>
        <strong>정확도 100% (쿠팡윙 화면·엑셀 원본 일치)</strong>
        <span>윙 엑셀·화면 셀 값과 1원·1개까지 일치합니다. (엑셀 30일 매출은 번들 제외 / 정산·보관비는 전일 마감 기준)</span>
       </div>
      </div>
     </article>
    </div>
    <div className="refresh-tip-bar">
     <Sparkles size={15}/>
     <span><b>추천 사용법:</b> 평소 재고·품절·주문 확인은 <b>[API만 빠르게 갱신]</b>, 출근 직후 입고·반출·광고·정산 점검은 <b>[전체 자료 새로고침]</b>, 특정 월/기간 손익은 돈의 흐름 카드에서 <b>[기간 조회]</b>(5~10초)를 눌러주세요.</span>
    </div>
    <div className="refresh-help-warning">
     <Info size={15}/>
     <span>{online?'수집 PC가 정상 연결되어 있습니다.':'수집 PC를 켜고 연결해야 갱신할 수 있습니다.'} 최근 완료된 자료(API 5분, 전체 1시간 이내)는 빠르게 재사용하며, 미로그인 시 이전 검증 자료를 안전하게 유지합니다.</span>
    </div>
   </div>
  </details>
  {Number.isFinite(finished)&&<small className="refresh-last-duration">최근 작업 실제 소요 {Math.floor(finished/60)}분 {finished%60}초 · {job?.state==='partial'?'일부 갱신':'작업 종료'}</small>}
 </div>
}
