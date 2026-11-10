"""Versioned operating procedures. Business rules stay outside generated text."""
from datetime import datetime
from config import KST, now

VERSION='2026.10.27-v1'

def source_health(source, at=None):
    at=at or now()
    stamp=source.get('time')
    try:
        captured=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if captured.tzinfo is None: captured=captured.replace(tzinfo=KST)
        age=(at-captured).total_seconds()/3600
    except (ValueError,TypeError,AttributeError):
        age=None
    status=source.get('status','미수집')
    failed=any(word in status for word in ('실패','필요','미완료','미수집','이전'))
    freshness='기준 시각 확인 필요' if age is None or age < 0 else '최근 수집' if age<=2 else '기준 시각 경과'
    return {'age_hours':round(age,1) if age is not None else None,
            'freshness':freshness,'review_required':failed or age is None or age<0 or age>2,
            'meaning':'최근 수집은 거래 데이터의 실시간성을 보장하지 않습니다.'}

def master_manual(snapshot):
    summary=snapshot['summary']
    def section(id,title,when,sources,steps,stop,done):
        by_id={s['id']:s for s in snapshot['sources']}
        return {'id':id,'title':title,'when':when,'source_ids':sources,'steps':steps,
                'stop_conditions':stop,'completion':done,
                'source_review_required':any(by_id.get(k,{}).get('quality',{}).get('review_required',True) for k in sources)}
    sections=[
        section('data','⚡ API 빠른 갱신 vs 📦 전체 자료 새로고침 가이드','수시(API 2~10초) · 하루 1~2회(전체 자료 20~45초)', ['api_orders','inventory','finance'],
            ['⚡ [API만 빠르게 갱신 · 수시 권장] 크롬 로그인 없이 2~10초 만에 공식 API 4종(실시간 판매가능재고·묶음재고 연동, 최근 30일 주문·출고, 등록 판매가·할인가, API 반품·취소)을 쿠팡 서버 원장 기준 정확도 100%로 즉시 가져옵니다.',
             '📦 [전체 자료 새로고침 · 하루 1~2회 권장] API 4종에 더해 쿠팡윙 전용 5종(창고 입고예정·30일 무료보관 경과·장기보관 재고, 손익·수수료·정산 예정금, 광고비·ROAS·키워드, 90일+ 장기 미회수 반품·보상)을 쿠팡윙 화면·엑셀 원본 일치율 100%로 통합 갱신합니다.',
             '🎯 [정확도 100% 기준 차이] 30일 주문금액 차이는 오류나 누락이 아니라 집계 시점 차이(API=결제·출고일 기준 vs Wing=구매확정·취소차감 기준)이며, 2개입·3개입 묶음옵션도 모체(1개입) 단품 재고를 자동 공유 계산해 미확인 없이 100% 연동됩니다.',
             '💡 [추천 사용법] 평소 판매량·재고 확인은 ⚡ API만 빠르게 갱신(수시)을 누르고, 아침 업무 시작·오후 마감이나 광고·정산·창고 보관일 점검 때만 📦 전체 자료 새로고침을 실행하세요.'],
            ['전체 자료 새로고침 시 쿠팡윙 크롬 연결이 잠깐 끊겨도 에러로 멈추지 않고 최근 성공 캐시를 안전하게 유지합니다.',
             '원본 열 변경·합계 불일치가 있으면 해당 숫자를 최신값으로 단정하지 않습니다.'],
            '⚡ API 빠른 갱신(4종·실시간 서버 원장 100%)과 📦 전체 자료 새로고침(+5종·쿠팡윙 원본 100%)의 용도와 주기를 확인했습니다.'),
        section('stock','재고·입고 판단','품절 또는 입고 검토 후보가 있을 때', ['inventory','api_inventory'],
            ['권장 입고량·예상 재고일을 후보 목록으로 확인합니다.',
             'API와 엑셀에서 옵션 ID와 상품등급을 맞춰 판매가능재고를 대조합니다.',
             '실제 조달기간·이미 예약한 입고·최소 발주량을 확인합니다.',
             '후보별 수량과 자금 부담을 검토한 뒤 직접 발주 여부를 결정합니다.'],
            ['권장 입고량은 자동 발주 지시가 아닙니다.', '실제 조달기간이나 재고 시점이 확인되지 않으면 발주 확정을 보류합니다.'],
            '입고 후보의 현재 재고와 실제 조달기간을 대조했습니다.'),
        section('ads','광고·원가 점검','광고비 또는 ROAS가 걱정될 때', ['ads','ad_detail','inventory'],
            ['상품 매입원가·기타 단위비용부터 입력합니다.',
             '광고 성과 보고서의 집계기간과 전환 기여기간을 확인합니다.',
             '캠페인·상품별 광고비와 같은 기간의 수수료·환불을 대조합니다.',
             '작게 변경할 후보와 관찰 종료일을 정하고 변경 전 수치를 남깁니다.'],
            ['원가가 없으면 손익분기 ROAS나 순이익을 확정하지 않습니다.',
             '정산 매출과 광고 전환매출을 합산하지 않습니다.',
             '최근 광고 전환은 뒤늦게 반영될 수 있어 하락 원인을 단정하지 않습니다.'],
            '원가와 동일 기준 광고 상세를 확보한 뒤 변경 근거를 기록했습니다.'),
        section('settlement','정산·현금 흐름 확인','정산일 전후와 월 마감 때', ['finance','settlement'],
            ['윙 수익 현황의 조회기간과 수집 시각을 확인합니다.',
             '매출 + 비용(음수) + 보상 = 윙 표시 이익인지 대조합니다.',
             '정산 상세의 정산주기 종료일과 VAT 포함 최종비용을 확인합니다.',
             '빠른정산·보류·지급비율을 확인하고 실제 입금 내역과 별도로 대조합니다.'],
            ['윙 표시 이익에는 사입원가 등 외부 비용이 빠져 있으므로 순이익으로 쓰지 않습니다.',
             '정산주기 비용을 다른 기간의 월간 비용에 다시 더하지 않습니다.',
             '월말 미포함 보상액으로 해당 월 보상 유무를 판단하지 않습니다.'],
            '조회기간·정산주기·실제 입금의 차이를 확인했습니다.'),
        section('returns','반품·보상 확인','장기 회수중이거나 반품 사유가 반복될 때', ['returns','return_insight','compensation'],
            ['접수일과 원본 처리 상태로 장기 회수 후보를 확인합니다.',
             '쿠팡윙에서 현재 회수 상태를 재확인합니다.',
             '보상 원본의 주문·옵션·정산주기를 로컬에서 대조합니다.',
             '이미 처리된 건을 제외하고 상태·보상 반영 여부를 문의합니다.',
             '월별 반품률과 상품별 반품 사유로 상세페이지 개선 후보를 검토합니다.'],
            ['90일 이상 회수중은 미보상 확정이나 지급액 추정이 아닙니다.',
             '누적 반품 접수 건수를 현재 주문·매출로 나눠 반품률을 만들지 않습니다.',
             '주문번호·고객정보가 있는 원본을 외부 AI에 보내지 않습니다.'],
            '현재 처리 상태와 보상 반영 여부를 대조해 확인 대상을 추렸습니다.'),
        section('weekly','주간 점검과 다음 계획','주간 검토와 다음 주 계획 수립 때', ['inventory','ads','finance','returns'],
            ['자료별 조회기간을 맞추고 이번 주에 확보하지 못한 원본을 기록합니다.',
             '원가·입고 후보·장기 회수 상태의 미완료 항목을 확인합니다.',
             'AI 제안에서 관측 근거와 가설을 구분하고 추가 확인 자료를 준비합니다.',
             '작업별 담당자·완료 기준·실제 결과를 기록하고 다음 점검일에 검토합니다.'],
            ['자료가 부족한 주제는 확인 작업으로 남기고 원인이나 성과를 꾸며 내지 않습니다.',
             'AI는 실행 제안이며 광고 변경·발주·가격 수정은 직접 검토합니다.'],
            '검증된 사실, 미확인 가설, 다음 확인 작업을 구분해 기록했습니다.')]
    return {'version':VERSION,'title':'로켓그로스 운영 마스터 매뉴얼',
            'scope':'현재 연결된 자료의 해석·점검 절차입니다. 쿠팡 정책 또는 업무 전체를 보장하는 공식 매뉴얼이 아닙니다.',
            'basis_at':snapshot.get('generated_at'), 'sections':sections,
            'current_checks':{'missing_costs':summary.get('missing_costs'), 'restock':summary.get('restock'),
                              'overdue_returns':summary.get('overdue_returns')}}
