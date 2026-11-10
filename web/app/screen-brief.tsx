"use client";
import {ArrowRight} from 'lucide-react';
import {aiReview,returnOverview,sourceOverview} from '../lib/screen-review';
type Row=Record<string,any>;
const count=(v:any)=>v==null?'미확인':Number(v).toLocaleString('ko-KR');
export default function ScreenBrief({view,s,onMetric,onNavigate,onCosts,onChat}:{view:string;s:Row;onMetric:(key:string)=>void;onNavigate:(view:string)=>void;onCosts:()=>void;onChat:()=>void}){
 const r=returnOverview(s),health=sourceOverview(s),report=s.ai?.status==='ready'?s.ai:s.ai?.previous;
 const settings:Record<string,{title:string;description:string;facts:string[];action:string;run:()=>void}>={
  inventory:{title:'입고할 상품과 묶여 있는 재고를 찾습니다',description:'판매금액이 큰 순으로 정렬했습니다. 상품을 누르면 리드타임·입고 예정·권장 수량을 함께 볼 수 있어요.',facts:[`입고 검토 ${count(s.summary?.restock)}개 항목`,`품절 ${count(s.summary?.out_of_stock)}개 항목`,`원가 미입력 ${count(s.summary?.missing_costs)}개 항목`],action:'매입원가 입력',run:onCosts},
  finance:{title:'같은 기간의 매출 − 비용으로 수익을 확인합니다',description:'아래는 마지막 검증 기간입니다. 매입원가·추가 비용이 확인되기 전에는 순이익을 확정하지 않습니다.',facts:[s.finance?.[0]?`${s.finance[0].start} ~ ${s.finance[0].end}`:'수익 자료 미확보','주문금액·광고 전환매출 합산 제외'],action:'판매금액 집계 기준',run:()=>onMetric('revenue30')},
  returns:{title:'장기 회수 건부터 실제 처리 상태를 확인하세요',description:'보상·정산 내역과 대조할 목록입니다. 접수 건수는 반품 수량이나 전체 판매의 반품률과 다릅니다.',facts:[`90일 이상 회수중 ${count(r.overdue)}건`,`전체 회수중 ${count(r.collecting)}건`,`원본 접수 ${count(r.total)}건`],action:'장기 회수 내역',run:()=>onMetric('overdue_returns')},
  ai:{title:'현재 상황을 질문하고, 근거와 실행 순서를 확인하세요',description:'대화에는 연결된 운영 자료와 저장한 원가를 제공합니다. 아래 보고서는 생성 시점의 분석입니다.',facts:[report?.model||'모델 미확인',aiReview(s,report)||'자료 갱신 여부 확인됨','API 분석은 별도 사용료'],action:'현 상황 AI와 논의',run:onChat},
  sources:{title:'지금 믿고 읽을 범위와 빠진 자료를 구분합니다',description:'연결 성공과 자료의 최신 여부는 다릅니다. 실패·미수집 자료를 먼저 표시했습니다. 시각은 수집 후 2시간 기준으로 점검하며, 수집 실패도 별도 표시합니다.',facts:[`기준 이내 ${health.current}개`,`기준 재확인 ${health.review}개`,`시각 미확인 ${health.missing}개`],action:'미연결 범위 보기',run:()=>document.getElementById('source-gaps')?.scrollIntoView({behavior:'smooth',block:'start'})},
  manual:{title:'점검을 실제 업무의 완료 기준으로 연결합니다',description:'주제를 선택하고 확인 절차를 따라가세요. 체크는 업무 완료나 쿠팡 처리 완료를 대신하지 않습니다.',facts:[`${s.manual?.sections?.length??0}개 운영 주제`,'기록은 현재 브라우저에 저장'],action:'자료 상태 먼저 확인',run:()=>onNavigate('sources')},
 };
 const item=settings[view];if(!item)return null;
 return <section className="screen-brief" aria-label="이 화면 활용 안내"><div><h2>{item.title}</h2><p>{item.description}</p><div className="screen-facts">{item.facts.map(f=><span key={f}>{f}</span>)}</div></div><button className="secondary" onClick={item.run}>{item.action}<ArrowRight size={16}/></button></section>;
}
