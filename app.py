import json
import html
import os
import subprocess
import importlib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from config import ROOT, RAW, DATA, now
from src.file_loader import load_data, save_upload
from src.calculator import master_for, save_master, enrich, strict_total, claims_text
from src.parsers import rows, inspect_workbook
from src.coupang_api import CoupangReader
from src.credential_store import load_credentials, save_credentials, delete_credentials
from src.browser_bridge import Bridge
from src.browser_collect import collect as collect_browser
import src.browser_bridge as bridge_module
from src.finance import load_finance, settlement_schedule, ad_billing, ad_campaign_screen, kst_timestamp
from src.returns_insights import latest_return_insight
from src.compensation import load_compensation, load_ad_campaigns, attach_compensation
from src.ad_performance import load_ad_performance
from src.ad_live import load_live_ad
from src.settlement_exports import load_settlement_exports

st.set_page_config(page_title='로켓그로스 · 운영 대시보드',page_icon='◈',layout='wide')
st.sidebar.link_button('↗ 비공개 웹 대시보드', 'https://rocket-desk-watnimall.mindery1.chatgpt.site', use_container_width=True)
@st.cache_resource
def browser_bridge():
    try: return Bridge().start()
    except OSError: return None
bridge=browser_bridge()
# Keep the active local pairing when Streamlit reruns after a collector job update.
# Existing Bridge methods resolve JOBS from this module's dictionary.
if not any(job['kind']=='ad_performance' for job in bridge_module.JOBS) or not hasattr(bridge_module.Bridge,'MAX_ACTIVE_SECONDS'):
    importlib.reload(bridge_module)
if bridge:
    # Streamlit can keep a Bridge instance created before the source module was
    # reloaded. Update that instance's job list without discarding its pairing.
    bridge.queue.__func__.__globals__['JOBS']=bridge_module.JOBS
    bridge.__class__.MAX_ACTIVE_SECONDS=bridge_module.Bridge.MAX_ACTIVE_SECONDS
    bridge.__class__.expire=bridge_module.Bridge.expire
    from src import collector_relay
    if not hasattr(collector_relay, 'PAIRING_PERSISTENCE'):
        importlib.reload(collector_relay)
    collector_relay.start_relay(bridge)
if 'credential_bootstrapped' not in st.session_state:
    st.session_state['credential_bootstrapped']=True
    try:
        stored=load_credentials()
        st.session_state['credential_saved']=bool(stored)
        if stored: st.session_state['credentials']=stored
    except Exception as ex:
        st.session_state['credential_saved']=False
        st.session_state['credential_warning']=str(ex)
def browser_summary(state):
    sources={s.get('kind'):s for s in state.get('sources',[])}
    labels={'inventory':'재고 화면','settlement':'정산 화면','ad_billing':'광고비 화면','customer_returns':'반품분석 화면','ad_performance':'광고센터 성과 화면'}
    parts=[]
    for kind,label in labels.items():
        source=sources.get(kind)
        if not source: continue
        parts.append(label+(' 완료' if source.get('status','').startswith(('수집 완료','화면 수집 완료')) else ' '+source.get('status','확인 필요')))
    for kind,prefix,label in [('inventory','inventory_health_sku_info_','재고'),('inventory','inventory_health_creturn_v2_info_','반품'),('ad_billing','cmg_settlement_detail_','광고 상세')]:
        source=sources.get(kind)
        if source:
            done=any(item.get('status')=='파일 저장 완료' and item.get('name','').startswith(prefix) for item in source.get('downloads',[]))
            parts.append(label+' 엑셀 '+('새 파일 확인' if done else '이번 자동 저장 미확인'))
    return '브라우저 새로고침 '+state['status']+' · '+' · '.join(parts)
def refresh_all(full=False):
    if full:
        try:
            with st.spinner('쿠팡윙·광고센터 화면과 엑셀 원본을 확인하는 중입니다…'):
                browser_state=collect_browser()
            st.session_state['browser_message']='브라우저 자동 수집 · '+browser_summary(browser_state)
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as ex:
            st.session_state['browser_message']='브라우저 화면 수집 실패 · '+str(ex)
    else:
        st.session_state['browser_message']='빠른 새로고침 · API를 다시 조회하고 저장된 원본을 확인했습니다. 윙 화면·엑셀은 각 항목에 표시된 마지막 수집값입니다.'
    if st.session_state.get('credentials'):
        with st.spinner('쿠팡 공식 API 조회 중…'):
            try:
                result=CoupangReader(**st.session_state['credentials']).collect()
                st.session_state['api_message']='API 조회 완료 · '+result['fetched_at']
            except Exception as ex: st.session_state['api_message']='API 조회 실패 · '+str(ex)
    else: st.session_state['api_message']='파일 재검색 완료 · API 미연결로 쿠팡 서버 직접 조회는 아직 불가'
    st.session_state.pop('loaded',None)
st.markdown('''<style>
.block-container{padding:4rem 2.7rem 3rem;max-width:1700px}
[data-testid="stSidebar"]{background:#142E3D;color:#e8f2f2}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,[data-testid="stSidebar"] p,[data-testid="stSidebar"] label{color:#e8f2f2}
[data-testid="stSidebar"] .stCaption{color:#adc2cc}
h1{font-size:2.05rem!important;letter-spacing:-1.3px}h2{font-size:1.25rem!important}
.eyebrow{color:#087f72;font-size:12px;font-weight:750;letter-spacing:2px;margin-bottom:10px}
.subtext{color:#6c7e8a;margin-top:-12px;margin-bottom:24px;font-size:14px}
.metric{background:white;border:1px solid #e3e9ed;border-radius:14px;padding:21px 22px;min-height:153px}
.metric .label{font-size:13px;color:#617786;font-weight:600}.metric .value{font-size:29px;font-weight:750;letter-spacing:-1px;margin:12px 0 6px}.metric .help{font-size:12px;color:#7b8c97}
.section-note{background:#e8f3f0;border-left:3px solid #087f72;padding:15px 18px;border-radius:5px;color:#31534e;font-size:14px;margin:20px 0}
.source-tag{display:inline-block;background:#e7efec;color:#247164;font-size:11px;border-radius:20px;padding:4px 10px;margin-right:6px}
[data-testid="stVerticalBlockBorderWrapper"]{background:white;border-radius:12px}
.stButton>button{border-radius:8px}.stTabs [data-baseweb="tab-list"]{gap:24px}.stTabs [data-baseweb="tab"]{font-size:14px}
@media (max-width:600px){.block-container{padding:2rem 1rem 2rem}h1{font-size:1.65rem!important;letter-spacing:-.5px}.metric .value{font-size:24px}}
</style>''',unsafe_allow_html=True)

LABELS={'option_id':'옵션 ID','product_id':'등록상품 ID','sku_id':'SKU ID','product_name':'상품명','option_name':'옵션명','grade':'상품등급',
 'revenue':'매출액','sold_qty':'판매수량','stock_available':'판매가능재고','stock_inbound':'입고예정재고','doc_days':'쿠팡 예상 소진일',
 'restock_rec_qty':'추가입고 추천수량','restock_rec_date':'권장 입고일','stock_status':'재고 상태','storage_fee_mtd':'이번달 누적보관료',
 'rev_7d':'7일 매출','rev_30d':'30일 매출','qty_7d':'7일 판매수량','qty_30d':'30일 판매수량','returns_30d':'30일 반품수량',
 'forecast_1w':'1주 판매예측','forecast_5w':'5주 판매예측','forecast_10w':'10주 판매예측','long_stock':'61일 이상 보관재고',
 'unit_cost':'개당 사입원가','other_unit_cost':'개당 부대비용','commission_rate':'판매수수료율 % (VAT 별도)',
 'fulfillment_unit':'개당 입출고·배송비 (VAT 포함)','return_unit':'건당 반품비 (VAT 포함)','lead_days':'입고 준비일','target_margin':'목표 마진율 %',
 'model_cogs':'가정 매출원가','model_commission':'가정 판매수수료','model_fulfillment':'가정 입출고·배송비','contribution_before_unmatched':'미반영 비용 전 기여액',
 'request_date':'반품 접수일','return_no':'반품번호','order_no':'주문번호','reason':'반품 사유','return_grade':'검수 등급',
 'process_status':'처리 상태','elapsed_days':'경과일','overdue':'90일 이상 회수중','source_file':'출처 파일','inspection_no':'검수번호',
 'price_gap':'7일/30일 평균단가 차이 %','item_winner':'아이템위너','reg_date':'상품 등록일','grade_suffix':'옵션 ID 표기 등급',
 'return_qty':'반품 수량 (없으면 미제공)','disposed':'폐기 여부','return_type':'반품 유형',
 'compensation_amount':'보상 상세 기록액','compensation_period':'보상 정산주기',
 'before':'변경 전 재고','transferred':'이관완료','inbound_requested':'입고요청','inbound':'입고','allocating':'재고 배치중','delayed':'판매개시 지연',
 'outbound':'출고','reshipped':'재출고','returned':'고객반품','removed':'반출완료','adjusting':'처리중','lost':'분실/파손 확정',
 'after':'변경 후 재고','calculated_after':'계산한 변경 후 재고','difference':'검산 차이','loss_review':'보상 대조 검토',
 'age_1_30':'1~30일','age_31_45':'31~45일','age_46_60':'46~60일','age_61_120':'61~120일','age_121_180':'121~180일','age_181_plus':'181일 이상'}

def money(v): return '확인 필요' if v is None or pd.isna(v) else f'{v:,.0f}원'
def count(v): return '확인 필요' if v is None or pd.isna(v) else f'{v:,.0f}개'
def display_time(value): return str(value)[:16].replace('T',' ')+' KST' if value else '—'
def metric(label,value,help_text):
    st.markdown(f'<div class="metric"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div><div class="help">{html.escape(help_text)}</div></div>',unsafe_allow_html=True)
def table(df,cols=None,height=380):
    display=df[cols].copy() if cols else df.copy()
    st.dataframe(display.rename(columns=LABELS),hide_index=True,width='stretch',height=height)
def csv(df):
    out=df.rename(columns=LABELS).copy()
    # Protect spreadsheet clients from formula injection in user-entered product fields.
    for c in out.select_dtypes(include=['object','string']).columns:
        out[c]=out[c].map(lambda x:"'"+x if isinstance(x,str) and x.startswith(('=','+','-','@','\t','\r')) else x)
    return out.to_csv(index=False).encode('utf-8-sig')
def chart(fig):
    fig.update_layout(font_family='Malgun Gothic, sans-serif',font_color='#395363',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',margin=dict(t=20,b=20,l=10,r=10))
    st.plotly_chart(fig,width='stretch',config={'displaylogo':False})

with st.sidebar:
    st.markdown('### ◈ ROCKET DESK')
    st.caption('왓니몰 · 로켓그로스 운영실')
    st.divider()
    page=st.radio('메뉴',['한눈에 보기','상품별 손익','재고·입고','반품·보상 확인','원가 설정','자료실·연결'],label_visibility='collapsed')
    st.divider()
    period=st.selectbox('매출 집계 기간',['최근 30일','최근 7일'])
    days=30 if period=='최근 30일' else 7
    grade=st.selectbox('상품등급',['전체','NEW','반품-최상','반품-상','반품-중'])
    query=st.text_input('상품 검색',placeholder='상품명 또는 옵션 ID')
    easy=st.toggle('초보자 설명',value=True)
    st.divider()
    if st.button('↻ 새로고침',type='primary',width='stretch'):
        refresh_all()
    st.caption('빠른 새로고침은 공식 API 조회와 저장된 원본 확인만 실행합니다. 새 엑셀은 본문의 ‘화면·엑셀 원본 갱신’에서 받습니다.')
    st.link_button('쿠팡윙 열기 ↗','https://wing.coupang.com/tenants/rfm-inventory/management/list',width='stretch')

if 'loaded' not in st.session_state: st.session_state['loaded']=load_data()
bundle=st.session_state['loaded']
finance,finance_errors=load_finance()
schedule=settlement_schedule()
adbill=ad_billing()
campaign_screen=ad_campaign_screen()
compensation,compensation_errors=load_compensation()
campaigns,campaign_errors=load_ad_campaigns()
ad_performance,ad_performance_path,ad_performance_errors=load_ad_performance()
live_ad=load_live_ad()
settlement_details,settlement_detail_errors=load_settlement_exports()
inv=bundle['inventory']; ret=bundle['returns']; rec=bundle['reconciliation']
master=master_for(inv)
df=enrich(inv,master,days) if not inv.empty else pd.DataFrame()
if not df.empty:
    if grade!='전체': df=df[df.grade.eq(grade)]
    if query: df=df[df.product_name.fillna('').str.contains(query,case=False,regex=False)|df.option_id.str.contains(query,regex=False)]

st.markdown('<div class="eyebrow">ROCKET GROWTH / OPERATIONS</div>',unsafe_allow_html=True)
titles={'한눈에 보기':'오늘, 내 사업의 상태는?','상품별 손익':'매출에서 실제로 남는 돈','재고·입고':'재고는 가볍게, 품절은 미리','반품·보상 확인':'돌아오는 상품과 돈 확인하기','원가 설정':'우리 상품의 비용 기준','자료실·연결':'숫자의 출처를 확인하세요'}
st.title(titles[page])
if st.button('↻ 빠른 새로고침',key='refresh_main',type='primary'):
    refresh_all(); st.rerun()
if st.button('화면·엑셀 원본 갱신',key='refresh_originals'):
    refresh_all(full=True); st.rerun()
st.caption('평소: 빠른 새로고침(API). 하루 한 번 또는 정산 확인 시: 화면·엑셀 원본 갱신(약 1~3분, 쿠팡 응답에 따라 달라짐).')
st.markdown('<div class="subtext">실제 쿠팡 자료로 확인하고, 다음 할 일을 쉽게 찾으세요.</div>',unsafe_allow_html=True)
st.markdown(f'<span class="source-tag">원본 엑셀 기반</span><span class="source-tag">{html.escape(period)}</span><span class="source-tag">{len(df)}개 옵션·등급</span>',unsafe_allow_html=True)
st.caption('재고 파일 생성: '+display_time(bundle.get('inventory_time'))+'  |  파일 확인: '+display_time(bundle['scan_time']))
api_message=st.session_state.get('api_message')
browser_message=st.session_state.get('browser_message')
if api_message:
    (st.warning if api_message.startswith('API 조회 실패') else st.info)(api_message)
    if 'HTTP 403' in api_message and '공인 IP' in api_message:
        st.link_button('쿠팡윙에서 OPEN API 등록 IP 확인 ↗',
                       'https://wing.coupang.com/tenants/wing-account/vendor/salesinfo?isTARegion=false&currentPlatform=DESKTOP&currentLocale=ko')
        st.caption('쿠팡윙 → 판매자정보 → 추가판매정보 → OPEN API에서 이 PC의 현재 공인 IP 허용 여부를 확인하세요. IP가 바뀌면 API 조회는 실패하며 이전 API 값을 유지합니다.')
if browser_message:
    (st.warning if any(word in browser_message for word in ('시간 초과','확인 필요','미연결','실패','미확인')) else st.caption)(browser_message)
stale_sources=[]
for path,label,field in ((DATA/'browser_snapshot.json','브라우저 화면','received_at'),
                         (DATA/'api_snapshot.json','공식 API','fetched_at')):
    if not path.exists(): continue
    try:
        observed=datetime.fromisoformat(json.loads(path.read_text(encoding='utf-8'))[field])
        if now()-observed>timedelta(hours=2):
            stale_sources.append(f'{label} {display_time(observed.isoformat())}')
    except (ValueError,KeyError,TypeError,UnicodeError): continue
if stale_sources:
    st.warning('최신 자료 확인 필요 · '+ ' · '.join(stale_sources)+'에 마지막으로 수집됐습니다. 아래 수치는 지난 조회값이며 현재 실시간 값으로 보지 마세요.')
browser_snapshot_path=DATA/'browser_snapshot.json'
if browser_snapshot_path.exists():
    try:
        latest_sources=json.loads(browser_snapshot_path.read_text(encoding='utf-8')).get('sources',[])
        failed_sources=[s for s in latest_sources if s.get('status')!='수집 완료']
        if failed_sources:
            labels={'inventory':'재고','settlement':'정산','ad_billing':'광고비','customer_returns':'반품','ad_performance':'광고센터'}
            details=' · '.join(labels.get(s.get('kind'),s.get('kind','자료'))+' '+s.get('status','확인 필요') for s in failed_sources)
            st.warning('이번 브라우저 수집 미완료 · '+details+'. 해당 지표는 마지막 성공 자료를 표시합니다.')
    except (ValueError,UnicodeError,TypeError): pass
for error in finance_errors: st.warning(error)
for error in compensation_errors+campaign_errors+ad_performance_errors+settlement_detail_errors: st.warning(error)
if bundle['errors']:
    with st.expander(f'자료 확인 필요 {len(bundle["errors"])}건',expanded=True):
        for err in bundle['errors']: st.warning(err)
if inv.empty and page!='자료실·연결':
    st.info('자료실·연결에서 재고 엑셀을 업로드하면 시작할 수 있습니다.'); st.stop()

if page=='한눈에 보기':
    if finance:
        st.subheader('윙 정산에서 확인한 사업 전체 수익')
        selection=st.selectbox('정산 조회 기간',range(len(finance)),format_func=lambda i:finance[i]['start']+' ~ '+finance[i]['end'])
        fin=finance[selection]
        st.caption('사업 전체 기준 · 왼쪽 상품·매출 기간 필터와 별개 · VAT 포함 · 화면 수집 '+fin['captured_at'][:19].replace('T',' '))
        fc=st.columns(4)
        with fc[0]: metric('정산 화면 매출',money(fin['revenue']),'선택한 정산 기간의 매출')
        with fc[1]: metric('쿠팡 비용 합계',money(-fin['expenses']),'광고 + 풀필먼트 + 판매수수료')
        with fc[2]: metric('원가 차감 전 수익',money(fin['profit']),'윙 표시 이익 · 사입원가 미반영')
        with fc[3]: metric('정산 화면 보상액',money(fin['compensation']),'실제 입금 여부는 정산 리포트 대조 필요' if fin['complete_month'] else '월말 미포함 · 이 금액만으로 보상 유무 판단 불가')
        if easy: st.info('원가 차감 전 수익은 매출에서 쿠팡 비용을 빼고 화면의 보상액을 더한 값입니다. 사입원가·외부 비용이 빠져 있어 실제 순이익과 다릅니다.')
        with st.expander('광고·물류·수수료 구성과 원본 근거',expanded=True):
            components=pd.DataFrame({'항목':['광고비','풀필먼트서비스 비용','판매수수료'],'금액(원)':[-fin['ads'],-fin['fulfillment'],-fin['commission']]})
            st.dataframe(components,hide_index=True,width='stretch')
            if fin['shipping'] is not None:
                st.caption('풀필먼트 상세: 배송 '+money(-fin['shipping'])+' · 입출고 '+money(-fin['handling'])+' · 보관 '+money(-fin['storage'])+' · VAT '+money(-fin['fulfillment_vat']))
            st.link_button('이 숫자의 쿠팡 원본 화면',fin['source_url'])
            st.download_button('수집 근거 원문 저장',Path(fin['evidence']).read_bytes(),Path(fin['evidence']).name)
        if adbill:
            ad_time=adbill['captured_at'][:16].replace('T',' ')
            st.info(f'{adbill["month"]} 광고비 화면 · 청구 대상액 {money(adbill["bill"])} = 청구가능 {money(adbill["eligible"])} − 프로모션 {money(adbill["promotion"])} − 조정 {money(adbill["adjustment"])} + VAT {money(adbill["vat"])} · 화면 수집 {ad_time} KST')
            if campaign_screen:
                with st.expander(f'현재 광고 상세 화면 · 표시된 {len(campaign_screen["rows"])}개 캠페인'):
                    st.caption('윙 화면의 현재 페이지에 표시된 행입니다. 전체 캠페인 원본은 아래 공식 엑셀을 확인하세요. 화면 수집 '+campaign_screen['captured_at'][:19].replace('T',' ')+' KST')
                    st.dataframe(pd.DataFrame(campaign_screen['rows']),hide_index=True,width='stretch')
            if fin['start'][:7]==adbill['month']:
                comparison='표시 금액 일치' if -fin['ads']==adbill['bill'] else '표시 금액 차이 확인 필요'
                cutoff='' if fin['complete_month'] else ' 월별 광고비 화면에는 집계 마감일이 명시되지 않아 동일 기간 확정 대사는 아닙니다.'
                st.caption(f'{comparison} · 정산 {fin["start"]} ~ {fin["end"]} 광고비 {money(-fin["ads"])} · {adbill["month"]} 광고 청구 대상액 {money(adbill["bill"])}.{cutoff} 두 화면의 수집시각도 확인하세요.')
            else:
                st.caption(f'선택한 정산 기간 {fin["start"]} ~ {fin["end"]}의 광고비와 {adbill["month"]} 월별 청구액은 서로 다른 달이므로 직접 대조하지 않습니다.')
            if not campaigns.empty:
                campaign_total=int(campaigns.eligible.sum())
                campaign_path=RAW/campaigns.source_file.iloc[0]
                file_time=pd.Timestamp(campaign_path.stat().st_mtime,unit='s',tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M') if campaign_path.exists() else '시각 확인 필요'
                st.caption(f'광고 상세 엑셀 · 청구가능 금액 합계 {money(campaign_total)} · {len(campaigns)}개 캠페인 · 파일 시각 {file_time} KST. 화면과 금액이 다르면 수집 시점 차이를 먼저 확인하세요.')
                with st.expander('광고 캠페인 상세 · 원본 엑셀'):
                    st.dataframe(campaigns.rename(columns={'campaign':'캠페인','ad_type':'광고유형','impressions':'노출수','clicks':'클릭수','spend':'광고비(원)','eligible':'청구가능 광고비(원)','source_file':'원본 파일'}),hide_index=True,width='stretch')
                    st.caption('광고 상세 엑셀은 청구가능 광고비 기준입니다. VAT와 프로모션·조정은 위 광고비 화면에서 확인합니다.')
        if not compensation.empty:
            matched_comp=compensation[compensation.period_end.eq(fin['end'])]
            if not matched_comp.empty:
                comp_total=int(matched_comp.compensation_amount.sum())
                st.info(('보상 상세 엑셀 대조 일치' if comp_total==fin['compensation'] else '보상 상세 엑셀 대조 차이')+f' · {fin["end"]} 정산주기 {len(matched_comp)}건 합계 {money(comp_total)} · 윙 정산 화면 {money(fin["compensation"])}. 실제 은행 입금 확인과는 별개입니다.')
        if schedule:
            with st.expander(f'정산 리포트 {len(schedule)}건 · 지급일과 매출인식일 구분'):
                st.caption('이 표는 화면에 표시된 리포트 금액입니다. 미래 정산일이 포함되므로 실제 입금 합계로 보지 않습니다. 빠른정산과 이월 비용도 섞여 있어 매출이나 이익과 직접 비교할 수 없습니다.')
                payment_rows=pd.DataFrame(schedule,columns=['정산일','정산유형','지급비율(%)','매출인식일','화면의 최종지급액(원)'])
                st.dataframe(payment_rows,hide_index=True,width='stretch',height=350)
                st.download_button('정산 리포트 목록 CSV',csv(payment_rows),'settlement_schedule.csv','text/csv')
        if settlement_details:
            with st.expander('정산 상세 원본 엑셀 · 확인된 주간 범위'):
                st.caption('아래 금액은 각 엑셀의 정산주기 종료일 기준이며 VAT 포함 비용입니다. 위 월간 정산 화면, 현재 광고비, 실제 지급액과 기간·기준이 달라 합산하지 않습니다. 같은 유형·주기의 재다운로드는 최신 파일 한 건만 사용합니다.')
                detail_rows=pd.DataFrame(settlement_details)
                st.dataframe(detail_rows.rename(columns={'period_end':'정산주기 종료일','report':'리포트','part':'세부 항목','amount':'비용(VAT 포함, 원)','sales':'매출금액(원)','rows':'거래 행수','source_file':'원본 파일'}),hide_index=True,width='stretch')
                st.caption('판매수수료 리포트에는 주문 정산취소의 음수 행이 포함됩니다. 보상 원본은 반품·보상 확인 메뉴에서 별도로 대조합니다.')
                if list(RAW.glob('*-PPIR-*.xlsx')):
                    st.caption('리뷰 이벤트 비용 엑셀은 거래 행과 정산주기·합계가 없는 빈 원본입니다. 이 표에 0원으로 넣지 않았습니다.')
        st.divider()
    if not ad_performance.empty:
        first_day=ad_performance.date.min().strftime('%Y-%m-%d')
        last_day=ad_performance.date.max().strftime('%Y-%m-%d')
        ad_spend=int(ad_performance.spend.sum())
        ad_sales=int(ad_performance.sales_14d.sum())
        st.subheader('광고센터 상품별 성과')
        if live_ad:
            st.info(f'광고센터 이번달 화면 · {live_ad["start"]} ~ {live_ad["end"]} · 집행 광고비 {money(live_ad["spend"])} · 광고 전환 매출 {money(live_ad["sales"])} · 광고 수익률 {live_ad["roas"]:,.2f}% · 수집 {display_time(live_ad["captured_at"])}. 아래 상품별 엑셀은 별도 생성 시점의 자료입니다.')
        st.caption(f'공식 광고센터 엑셀 · {first_day} ~ {last_day} · {len(ad_performance):,}행 · 파일 생성 {display_time(pd.Timestamp(ad_performance_path.stat().st_mtime,unit="s",tz="UTC").tz_convert("Asia/Seoul").isoformat())}')
        ad_cards=st.columns(4)
        with ad_cards[0]: metric('집행 광고비',money(ad_spend),'광고 성과 보고서 기준 · VAT 별도')
        with ad_cards[1]: metric('광고 클릭수',f'{int(ad_performance.clicks.sum()):,}회','조회 기간 광고 클릭')
        with ad_cards[2]: metric('14일 전환 매출',money(ad_sales),'광고 기여 기준 · 정산 매출과 별개')
        with ad_cards[3]: metric('14일 광고 수익률',f'{ad_sales/ad_spend*100:,.1f}%' if ad_spend else '산출 불가','14일 전환 매출 ÷ 집행 광고비')
        if easy: st.info('광고 수익률 100%는 광고비 1원당 광고 기여 매출 1원을 뜻합니다. 상품 원가·쿠팡 수수료가 빠져 있어 이익률이 아닙니다. 최근 날짜의 14일 전환은 이후 바뀔 수 있습니다.')
        st.caption('광고센터의 집행 광고비와 윙의 청구가능 광고비·VAT 포함 정산 광고비는 집계 기준과 반영 시각이 달라 동일 금액으로 단정하지 않습니다.')
        with st.expander('일별 광고 성과와 원본'):
            daily=ad_performance.groupby('date',as_index=False)[['impressions','clicks','spend','orders_14d','sales_14d']].sum()
            daily.date=daily.date.dt.strftime('%Y-%m-%d')
            trend=daily.rename(columns={'date':'날짜','spend':'집행 광고비','sales_14d':'14일 전환 매출'}).melt('날짜',value_vars=['집행 광고비','14일 전환 매출'],var_name='지표',value_name='금액')
            chart(px.line(trend,x='날짜',y='금액',color='지표',markers=True,labels={'금액':'원'}).update_layout(height=340))
            st.dataframe(daily.rename(columns={'date':'날짜','impressions':'노출수','clicks':'클릭수','spend':'집행 광고비','orders_14d':'14일 전환 주문수','sales_14d':'14일 전환 매출'}),hide_index=True,width='stretch')
            by_option=ad_performance.groupby(['option_id','product'],as_index=False)[['impressions','clicks','spend']].sum().sort_values('spend',ascending=False)
            st.caption('아래 상품표는 광고가 집행된 옵션 기준입니다. 전환이 발생한 상품의 옵션 ID는 원본에서 별도 열이므로 상품별 전환매출을 이 표에 합산하지 않습니다.')
            st.dataframe(by_option.rename(columns={'option_id':'광고집행 옵션 ID','product':'광고집행 상품명','impressions':'노출수','clicks':'클릭수','spend':'집행 광고비'}),hide_index=True,width='stretch')
            st.download_button('광고 성과 원본 엑셀 다운로드',ad_performance_path.read_bytes(),ad_performance_path.name,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        st.divider()
    st.subheader('상품별 최근 매출과 현재 재고')
    c=st.columns(4)
    with c[0]: metric(period+' 매출',money(strict_total(df.revenue)),'번들 판매 제외 · 정산 확정액과 다를 수 있어요')
    with c[1]: metric('확정 순이익','산출 대기','사입원가·정산·광고비의 동일 기간 대사가 필요해요')
    with c[2]: metric('엑셀 표시 재고',count(strict_total(df.stock_available)),'현재 필터 · 재고 파일 생성 시점 기준')
    with c[3]: metric('확인된 이번달 보관료',money(df.storage_fee_mtd.sum(min_count=1)),f'미제공 {int(df.storage_fee_mtd.isna().sum())}행 제외 · 전일 기준')
    if (DATA/'api_snapshot.json').exists():
        api_overview=json.loads((DATA/'api_snapshot.json').read_text(encoding='utf-8'))
        api_total=sum(int(item['inventoryDetails']['totalOrderableQuantity']) for item in api_overview['inventory'])
        st.caption(f'공식 API 전체 재고 {api_total:,}개 · {len(api_overview["inventory"]):,}개 옵션 · 조회 {api_overview["fetched_at"][:19].replace("T"," ")} KST. 위 엑셀 재고는 현재 필터와 엑셀 추출 범위에 따른 값입니다. 옵션별 대조는 자료실·연결 → API 연결에서 확인하세요.')
    st.markdown('')
    a,b=st.columns([1.35,1])
    with a,st.container(border=True):
        st.subheader('먼저 확인할 일')
        urgent=df[df.restock_alert]
        if not urgent.empty:
            for _,r in urgent.sort_values('restock_rec_qty',ascending=False).head(2).iterrows():
                st.warning(f'입고 검토 · {r.product_name} / {r.option_name} — 예상 {r.doc_days:g}일, 추천 {r.restock_rec_qty:g}개, 권장일 {r.restock_rec_date}')
            if len(urgent)>2: st.caption(f'외 {len(urgent)-2}개 · 재고·입고에서 전체 추천을 확인하세요.')
        else: st.success('현재 필터에서 추가입고 추천이 있는 임박 상품이 없습니다.')
        overdue=int(ret.overdue.sum()) if not ret.empty else 0
        st.info(f'장기 미회수 반품 {overdue}건 · 반품·보상 확인에서 처리 상태와 지급 여부를 확인하세요. (전체 반품자료 기준)')
        missing=int(df.unit_cost.isna().sum())
        st.info(f'원가 미입력 {missing}개 옵션·등급 · 사입원가를 입력하면 비용 시뮬레이션을 볼 수 있어요.')
        if df.price_alert.any(): st.warning(f'평균단가 차이 30% 이상 {int(df.price_alert.sum())}개 · 번들 제외 여부와 할인을 확인하세요.')
    with b,st.container(border=True):
        st.subheader('매출이 큰 상품')
        top=df.nlargest(6,'revenue').copy()
        top['상품']=top.product_name.str.slice(0,17)+' · '+top.option_name.fillna('').str.slice(0,9)
        chart(px.bar(top.sort_values('revenue'),x='revenue',y='상품',orientation='h',color_discrete_sequence=['#098879'],labels={'revenue':'매출액 (원)'}).update_layout(height=300))
    if easy: st.markdown('<div class="section-note"><b>매출 ≠ 이익 ≠ 입금액</b><br>매출은 판매된 금액, 이익은 원가와 모든 비용을 뺀 돈, 정산 입금액은 쿠팡이 실제로 지급한 돈입니다. 세 금액을 서로 바꿔 읽지 마세요.</div>',unsafe_allow_html=True)
    st.subheader('상품별 운영 현황')
    table(df,['product_name','option_name','grade','revenue','sold_qty','stock_available','doc_days','stock_status','storage_fee_mtd'])
    st.download_button('현재 표 CSV 다운로드',csv(df),'rocket_overview.csv','text/csv')

elif page=='상품별 손익':
    st.warning('확정 순이익은 아직 계산할 수 없습니다. 아래는 입력한 비용만 반영한 시뮬레이션입니다. 광고·보관·반품·환불·보상금·세금은 미반영입니다.')
    if easy: st.write('최근 30일 매출과 이번달 보관료는 기간이 다릅니다. 반품 접수 건수도 판매 수량과 같은 단위가 아닙니다. 서로 섞어 정확한 이익처럼 표시하지 않습니다.')
    if df.empty: st.info('검색 조건에 맞는 상품이 없습니다.')
    else:
        idx=st.selectbox('상품 선택',df.index,format_func=lambda i:df.loc[i,'product_name']+' / '+str(df.loc[i,'option_name']))
        r=df.loc[idx]
        if pd.isna(r.contribution_before_unmatched): st.info('원가 설정에서 사입원가·부대비용·수수료율·입출고배송비를 모두 입력해 주세요. 실제 0원인 비용은 0을 입력합니다.')
        else:
            chart(go.Figure(go.Waterfall(x=['매출','가정 원가','가정 수수료','가정 물류비','미반영 비용 전 기여액'],
                y=[r.revenue,-r.model_cogs,-r.model_commission,-r.model_fulfillment,0],measure=['absolute','relative','relative','relative','total'],
                increasing={'marker':{'color':'#0c8c7b'}},decreasing={'marker':{'color':'#e7a26e'}},totals={'marker':{'color':'#244858'}})).update_layout(height=380))
        table(df,['product_name','option_name','revenue','unit_cost','model_cogs','model_commission','model_fulfillment','contribution_before_unmatched'])
        st.download_button('손익 시뮬레이션 CSV',csv(df),'rocket_cost_simulation.csv','text/csv')

elif page=='재고·입고':
    c=st.columns(3)
    with c[0]: metric('품절 옵션·등급',str(int(df.out_of_stock.sum()))+'개','품절은 재고가 0개인 상태예요')
    with c[1]: metric('추가입고 추천',count(df.restock_rec_qty.sum(min_count=1)),'쿠팡 추천값 · 입고 신청은 자동으로 하지 않아요')
    with c[2]: metric('61일 이상 보관재고',count(df.long_stock.sum(min_count=1)),'보관료와 판매 속도를 함께 확인하세요')
    a,b=st.columns(2)
    with a,st.container(border=True):
        st.subheader('보관기간별 재고')
        cols=['age_1_30','age_31_45','age_46_60','age_61_120','age_121_180','age_181_plus']
        totals=df[cols].sum(min_count=1)
        chart(px.bar(x=[LABELS[x] for x in cols],y=totals,color_discrete_sequence=['#238d80'],labels={'x':'보관기간','y':'수량'}).update_layout(height=290))
        st.caption('보관기간 분류는 전일 기준, 판매가능재고는 파일 생성 시점 기준이라 합계가 다를 수 있습니다.')
    with b,st.container(border=True):
        st.subheader('재고와 쿠팡 판매예측')
        top=df.nlargest(8,'forecast_5w').copy()
        top['상품']=top.product_name.str.slice(0,13)+' / '+top.option_name.fillna('')
        chart(px.bar(top,x='상품',y=['stock_available','forecast_1w','forecast_5w','forecast_10w'],barmode='group',
                     color_discrete_sequence=['#183b4b','#2d9a86','#83cbb9','#cfddd5'],labels={'value':'수량','variable':'항목'}).update_layout(height=290))
    table(df,['product_name','option_name','grade','stock_available','stock_inbound','doc_days','restock_rec_qty','restock_rec_date','long_stock','stock_status'])
    st.download_button('입고 검토표 CSV',csv(df[df.restock_alert]),'restock_review.csv','text/csv')
    with st.expander('재고변동 검산 · 원본의 부호 규칙 적용'):
        st.write('원본에 표시된 변경 후 재고 공식은 각 변동값을 부호 그대로 더하는 방식입니다. 출고를 다시 빼서 이중 차감하지 않습니다.')
        st.caption(rec.attrs.get('period','조회기간 미확인'))
        if rec.empty: st.info('현재 선택된 재고변동 보고서에는 상세 행이 없습니다. 재고 손실이 없다는 의미는 아닙니다.')
        else: table(rec)

elif page=='반품·보상 확인':
    st.caption('반품 보고서는 전체 조회 범위입니다. 왼쪽 매출 기간·상품등급 필터를 적용하지 않습니다. 상품 검색만 적용합니다.')
    return_insight=latest_return_insight()
    if return_insight:
        st.info(f'윙 반품분석 화면 · {return_insight["month"]}월 반품률 {return_insight["rate"]:g}%'
                + (f' · 분석 상품목록 {return_insight["products"]:,}건' if return_insight['products'] is not None else '')
                + f' · 쿠팡 자료 업데이트 {return_insight["updated"]} · 화면 수집 {return_insight["captured_at"][:19].replace("T"," ")} KST. 아래 전체 이력 엑셀의 행 수와 집계 단위가 다릅니다.')
    rt=attach_compensation(ret,compensation)
    if query and not rt.empty: rt=rt[rt.product_name.fillna('').str.contains(query,case=False,regex=False)|rt.option_id.str.contains(query,regex=False)]
    if rt.empty: st.info('조건에 맞는 반품 자료가 없습니다.')
    else:
        c=st.columns(3)
        with c[0]: metric('반품 내역',f'{len(rt):,}행','수량 열이 없어 상품 개수로 간주하지 않아요')
        with c[1]: metric('90일 이상 회수중',f'{int(rt.overdue.sum()):,}건','보상 지급 여부 대조가 필요한 후보예요')
        with c[2]: metric('폐기 표시',f'{int(rt.disposed.sum()):,}행','수량·원가 확인 후 손실을 산정해요')
        if not compensation.empty:
            compensated=int(rt.compensation_amount.notna().sum())
            overdue_compensated=int((rt.overdue & rt.compensation_amount.notna()).sum())
            st.success(f'재고 손실 보상 엑셀 {len(compensation)}건 · 합계 {money(compensation.compensation_amount.sum())}. 현재 반품 자료에서 주문번호·옵션 ID로 {compensated}건 대조됐고, 장기 회수중 {int(rt.overdue.sum())}건 중 {overdue_compensated}건에도 보상 기록이 있습니다. 정산 반영 기록이며 실제 입금 확인은 별도입니다.')
        if easy: st.info('90일 이상 회수중은 확인 대상입니다. 보상 기록이 없는 건도 다른 정산주기에 지급됐을 수 있으므로 미지급액으로 합산하지 않습니다.')
        a,b=st.columns(2)
        with a:
            status=rt.process_status.value_counts().reset_index(); status.columns=['처리상태','건수']
            chart(px.bar(status,x='처리상태',y='건수',color_discrete_sequence=['#168d7d']).update_layout(height=300))
        with b:
            grades=rt.return_grade.fillna('미표시').value_counts().reset_index(); grades.columns=['검수등급','건수']
            chart(px.bar(grades,x='검수등급',y='건수',color_discrete_sequence=['#49758b']).update_layout(height=300))
        only=st.checkbox('90일 이상 회수중만 보기',value=True)
        shown=rt[rt.overdue] if only else rt
        table(shown,['request_date','return_no','order_no','option_id','product_name','reason','return_grade','process_status','elapsed_days','compensation_amount','compensation_period'])
        with st.expander('쿠팡확인요청 초안 · 복사해서 사용',expanded=True):
            st.code(claims_text(rt),language=None)
            st.download_button('확인요청 초안 저장',claims_text(rt).encode('utf-8-sig'),'반품_확인요청.txt','text/plain')
            st.link_button('윙 온라인문의 열기','https://wing.coupang.com/partner/qna/faq/list')
        st.download_button('반품 상세 CSV',csv(rt),'returns_review.csv','text/csv')

elif page=='원가 설정':
    st.info('빈칸은 미입력입니다. 실제 비용이 없는 경우에만 0을 입력하세요. 기본 수수료나 배송비를 임의로 적용하지 않습니다.')
    st.caption('사입원가·부대비용·물류비는 동일한 VAT 포함 기준으로 입력하세요. 판매수수료율만 VAT 별도 비율을 입력하며 계산 시 1.1을 곱합니다. 세무상 손익과는 다릅니다.')
    with st.form('cost_form'):
        edited=st.data_editor(master,hide_index=True,width='stretch',height=600,disabled=['option_id','product_name'],
            column_config={c:st.column_config.NumberColumn(LABELS[c],min_value=0,max_value=100 if c in ['commission_rate','target_margin'] else None,format='%.2f') for c in master if c not in ['option_id','product_name']}|
              {'option_id':st.column_config.TextColumn('옵션 ID'),'product_name':st.column_config.TextColumn('상품명')})
        if st.form_submit_button('원가 저장 · 재계산',type='primary'):
            try: save_master(edited); st.success('이 PC의 원가표에 저장했습니다. 다른 메뉴에서 새 계산을 확인하세요.')
            except Exception as ex: st.error(str(ex))
    st.download_button('원가표 CSV 다운로드',csv(edited),'master_cost.csv','text/csv')

else:
    tabs=st.tabs(['수집 현황','원본 전체 보기','API 연결','자료 추가','지표 설명','브라우저 연결'])
    with tabs[0]:
        st.subheader('자료마다 출처와 기준시각이 다릅니다')
        browser_path=DATA/'browser_snapshot.json'
        browser_data=json.loads(browser_path.read_text(encoding='utf-8')) if browser_path.exists() else {'sources':[]}
        browser_inventory=next((s for s in browser_data['sources'] if s.get('kind')=='inventory'),None)
        browser_ad_performance=next((s for s in browser_data['sources'] if s.get('kind')=='ad_performance'),None)
        api_path=DATA/'api_snapshot.json'
        api_data=json.loads(api_path.read_text(encoding='utf-8')) if api_path.exists() else None
        status=pd.DataFrame([
            ['브라우저 재고화면',browser_inventory['status'] if browser_inventory else '수집 대기',display_time(kst_timestamp(browser_inventory['captured_at'])) if browser_inventory and browser_inventory.get('captured_at') else '—','현재 화면 관찰 · 상세 분석은 검증된 원본 엑셀 기준'],
            ['재고 엑셀','연결됨' if not inv.empty else '자료 확인 필요',display_time(bundle.get('inventory_time')),'최근 7/30일 매출 · 재고 · 예측 · 보관기간'],
            ['반품 엑셀','연결됨' if not ret.empty else '자료 확인 필요',display_time(bundle.get('returns_time')),'원본 전체 이력 · 수량 열 없음'],
            ['재고변동 엑셀','빈 보고서' if rec.empty else '연결됨',display_time(bundle.get('reconciliation_time')),'조회기간 내 상세행 유무 확인'],
            ['정산 / CFS 상세','화면 합계 수집' if finance else '수집 대기',display_time(finance[0]['captured_at']) if finance else '—','기간별 매출·광고비·물류비·수수료·보상 / 상세 원본 대조 진행'],
            ['광고비 청구','청구 화면 확보' if adbill else '미수집',display_time(adbill['captured_at']) if adbill else '—','월 청구 대상액·캠페인 상세 엑셀'],
            ['광고 성과 보고서','상품별 엑셀 확보' if not ad_performance.empty else '미수집',display_time(pd.Timestamp(ad_performance_path.stat().st_mtime,unit='s',tz='UTC').tz_convert('Asia/Seoul').isoformat()) if ad_performance_path else '—',f'{len(ad_performance):,}행 · {ad_performance.date.min():%Y-%m-%d} ~ {ad_performance.date.max():%Y-%m-%d} · 새 보고서는 광고센터에서 생성 필요' if not ad_performance.empty else '광고센터 성과 보고서 원본 필요'],
            ['광고센터 이번달 화면','검증 완료' if live_ad else ('수치 확인 필요' if browser_ad_performance else '수집 대기'),display_time(live_ad['captured_at']) if live_ad else (display_time(kst_timestamp(browser_ad_performance['captured_at'])) if browser_ad_performance and browser_ad_performance.get('captured_at') else '—'),'Aside 또는 Chrome 광고센터의 현재 화면 수치 · 상품별 엑셀과 별도'],
            ['공식 주문·재고·상품 API','조회 완료' if api_data else '조회 대기',display_time(kst_timestamp(api_data['fetched_at'])) if api_data else '—',f'재고 {len(api_data["inventory"]):,}개 옵션 · 결제 주문 {len(api_data["orders"]):,}건 · 등록상품 {len(api_data.get("products",[])):,}개' if api_data else 'API 연결 탭에서 인증 · 조회 필요'],
        ],columns=['자료','상태','기준 시각','포함 내용 / 다음 단계'])
        st.dataframe(status,hide_index=True,width='stretch')
        st.caption('자료 수집이 안 된 것을 0건·0원으로 표시하지 않습니다. 화면 새로고침 시각과 쿠팡 자료 반영 시각은 다릅니다.')
        evidence_paths=sorted((DATA/'evidence').glob('*.txt'))
        if evidence_paths:
            with st.expander('직접 수집한 브라우저 원문 전체 보기'):
                evidence=st.selectbox('화면 수집 기록',evidence_paths,format_func=lambda p:p.name)
                st.text(evidence.read_text(encoding='utf-8'))
                st.download_button('화면 원문 다운로드',evidence.read_bytes(),evidence.name,key='evidence_download')
                st.caption('이 자료는 수집 당시 화면입니다. 새로고침으로 파일 확인만 한 경우 원문의 기준시각은 바뀌지 않습니다.')
        if browser_path.exists():
            st.write('브라우저에서 마지막으로 수집한 화면')
            for source in browser_data['sources']:
                capture=kst_timestamp(source['captured_at']) if source.get('captured_at') else '시각 없음'
                with st.expander(source['kind']+' · '+source['status']+' · '+capture+' KST'):
                    st.text(source.get('text',''))
                    st.caption(source.get('note',''))
                    st.write(source.get('downloads',[]))
                    st.write(source.get('completed_files',[]))
        if bundle['files']:
            files=pd.DataFrame(bundle['files']).rename(columns={'name':'원본 파일','kind':'구분','time':'파일 생성시각','rows':'상세 행수','status':'검증 상태','active':'현재 사용','bytes':'크기'})
            st.dataframe(files,hide_index=True,width='stretch')
    with tabs[1]:
        names=[f['name'] for f in bundle['files']]
        if names:
            selected=st.selectbox('원본 파일 선택',names)
            path=RAW/selected
            sheets=inspect_workbook(path)
            sheet=st.selectbox('시트 선택',[s['sheet'] for s in sheets])
            raw=rows(path,sheet)
            st.caption('상단 안내문·설명행·모든 열을 포함한 원본입니다. 분석표에서 생략된 정보도 여기에서 볼 수 있습니다.')
            st.dataframe(pd.DataFrame(raw).fillna('').astype(str),width='stretch',height=540)
            st.download_button('원본 엑셀 다운로드',path.read_bytes(),selected,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    with tabs[2]:
        st.write('쿠팡윙 → 판매자정보 → 추가판매정보 → Open API. 키를 채팅에 보내지 않고 이 PC의 화면에 직접 입력하세요.')
        st.link_button('추가판매정보 열기','https://wing.coupang.com/tenants/wing-account/vendor/salesinfo')
        st.link_button('공식 API 발급 안내','https://developers.coupang.com/ko/getting-started/issue-open-api-keynew')
        st.caption('기본은 현재 세션 메모리에만 보관합니다. 아래 저장을 선택하면 이 Windows 사용자 계정의 자격 증명 보관소에 저장해 대시보드 재실행 뒤에도 새로고침으로 조회합니다.')
        if st.session_state.get('credential_warning'): st.warning(st.session_state['credential_warning'])
        if st.session_state.get('credentials'):
            st.info('API 키 연결됨 · '+('Windows 자격 증명 보관소에 저장됨' if st.session_state.get('credential_saved') else '현재 세션에만 보관'))
        with st.form('api_connect',clear_on_submit=True):
            vendor=st.text_input('판매자 ID (A로 시작)')
            access=st.text_input('Access Key',type='password')
            secret=st.text_input('Secret Key',type='password')
            remember=st.checkbox('이 PC에 안전하게 저장해 다음 실행에도 자동 연결',value=st.session_state.get('credential_saved',False))
            if st.form_submit_button('연결하고 주문·재고·상품 조회',type='primary'):
                if not vendor or not access or not secret: st.error('세 항목을 모두 입력해 주세요.')
                else:
                    try:
                        credentials={'vendor':vendor.strip(),'access':access.strip(),'secret':secret.strip()}
                        reader=CoupangReader(**credentials)
                        st.session_state['credentials']=credentials
                        if remember:
                            save_credentials(credentials)
                            st.session_state['credential_saved']=True
                        elif st.session_state.get('credential_saved'):
                            delete_credentials()
                            st.session_state['credential_saved']=False
                    except Exception as ex: st.error(str(ex))
                    else:
                        with st.spinner('공식 API 연결 확인 중…'):
                            try:
                                snap=reader.collect()
                                st.success(f'조회 완료: 재고 {len(snap["inventory"])}개, 주문 {len(snap["orders"])}건, 등록상품 {len(snap.get("products",[]))}개. 이후 새로고침으로 다시 조회합니다.')
                            except Exception as ex:
                                st.warning('키를 연결했지만 첫 조회는 실패했습니다. 새로고침에서 재시도합니다. '+str(ex))
        if st.button('API 연결 해제 (저장된 키도 제거)'):
            try:
                if st.session_state.get('credential_saved'): delete_credentials()
                st.session_state.pop('credentials',None)
                st.session_state['credential_saved']=False
                st.success('API 연결과 저장된 키를 제거했습니다.')
            except Exception as ex: st.error(str(ex))
        if (DATA/'api_snapshot.json').exists():
            snap=json.loads((DATA/'api_snapshot.json').read_text(encoding='utf-8'))
            st.subheader('공식 API · 주문, 재고, 등록상품')
            st.caption('마지막 성공 조회: '+snap['fetched_at']+' · 주문 결제일 '+snap['paid_from']+' ~ '+snap['paid_to'])
            st.info('API 주문은 결제 기준 원자료입니다. 취소·반품·광고비·원가를 뺀 정산 매출이나 이익과 같지 않습니다.')
            api_inv=pd.json_normalize(snap['inventory'])
            product_rows=[]
            for product in snap.get('products',[]):
                for item in product.get('items',[]):
                    rg=item.get('rocketGrowthItemData') or item.get('rocketGrowthItem') or {}
                    if rg.get('vendorItemId') is not None:
                        product_rows.append({'option_id':str(rg['vendorItemId']),'등록상품 ID':str(product['sellerProductId']),
                            '등록상품명':product['sellerProductName'],'옵션명':item.get('itemName',''),
                            '등록상태':product.get('statusName','')})
            product_options=pd.DataFrame(product_rows)
            if not product_options.empty: product_options=product_options.drop_duplicates('option_id')
            order_rows=[]
            for order in snap['orders']:
                for item in order.get('orderItems',[]):
                    order_rows.append({'orderId':str(order['orderId']),'paidAt':order.get('paidAt'),**item})
            api_stock=sum(int(item['inventoryDetails']['totalOrderableQuantity']) for item in snap['inventory'])
            paid_units=sum(int(item['salesQuantity']) for item in order_rows)
            paid_gross=sum(Decimal(str(item['unitSalesPrice']))*int(item['salesQuantity']) for item in order_rows)
            cols=st.columns(4)
            with cols[0]: metric('API 재고 옵션',f'{len(api_inv):,}개','현재 쿠팡 API 목록 전체')
            with cols[1]: metric('API 주문가능재고',count(api_stock),'현재 API 조회 시각 기준')
            with cols[2]: metric('API 결제 주문',f'{len(snap["orders"]):,}건',f'상품 {paid_units:,}개 · 주문행 {len(order_rows):,}개')
            with cols[3]: metric('API 결제 상품금액',money(paid_gross),'취소·반품·비용 미반영 · 정산 매출과 별개')
            st.caption(f'상품 목록 API: 로켓그로스 또는 혼합 운영 등록상품 {len(snap.get("products",[])):,}개. 재고 API와 상품 목록 API는 대상 범위가 달라 옵션 개수가 같지 않을 수 있습니다.')
            if not api_inv.empty:
                api_inv['option_id']=api_inv.vendorItemId.astype(str)
                if not inv.empty:
                    excel_stock=inv.groupby('option_id',as_index=False).stock_available.sum()
                    api_stock_rows=api_inv[['option_id','inventoryDetails.totalOrderableQuantity']].rename(columns={'inventoryDetails.totalOrderableQuantity':'api_stock'})
                    comparison=excel_stock.merge(api_stock_rows,on='option_id',how='outer',indicator=True)
                    common=comparison[comparison['_merge'].eq('both')]
                    extra=comparison[comparison['_merge'].eq('right_only')]
                    mismatches=common[common.stock_available.ne(common.api_stock)]
                    st.write(f'엑셀 {len(excel_stock):,}개와 API {len(api_stock_rows):,}개 중 공통 {len(common):,}개 · 공통 재고 차이 {len(mismatches):,}개')
                    st.caption(f'API에만 있는 옵션 {len(extra):,}개 중 재고가 있는 옵션 {(extra.api_stock>0).sum():,}개, 합계 {extra.api_stock.sum():,.0f}개. 엑셀에 없는 이유는 원본의 추출 범위·상태·수집시각을 확인해야 합니다.')
                    comparison['구분']=comparison['_merge'].map({'both':'양쪽 모두','left_only':'엑셀만','right_only':'API만'}).astype(str)
                    comparison['재고 차이']=comparison.api_stock-comparison.stock_available
                    if not product_options.empty: comparison=comparison.merge(product_options,on='option_id',how='left')
                    else:
                        for col in ['등록상품명','옵션명','등록상태']: comparison[col]=''
                    named_extra=comparison.loc[comparison['구분'].eq('API만'),'등록상품명'].fillna('').astype(str).str.strip().ne('').sum()
                    st.caption(f'엑셀에 없는 API 재고 옵션 {len(extra):,}개 중 {named_extra:,}개는 등록상품 API의 상품명과 연결됐습니다. 이름이 연결되지 않은 옵션의 상태는 추가 확인이 필요합니다.')
                    st.dataframe(comparison[['option_id','등록상품명','옵션명','등록상태','구분','stock_available','api_stock','재고 차이']].rename(columns={'option_id':'옵션 ID','stock_available':'엑셀 재고','api_stock':'API 재고'}),hide_index=True,width='stretch')
            with st.expander('API 재고 원자료 전체 보기'):
                st.dataframe(api_inv,hide_index=True,width='stretch')
            with st.expander('API 주문 원자료 전체 보기'):
                st.dataframe(pd.DataFrame(order_rows),hide_index=True,width='stretch')
            with st.expander('API 등록상품 원자료 전체 보기'):
                st.dataframe(pd.DataFrame(snap.get('products',[])),hide_index=True,width='stretch')
    with tabs[3]:
        st.write('쿠팡윙에서 내려받은 원본 엑셀을 추가하세요. 파일은 이 PC에만 보관합니다.')
        uploads=st.file_uploader('엑셀 추가',type=['xlsx'],accept_multiple_files=True)
        if st.button('선택한 파일 가져오기'):
            for upload in uploads:
                try: save_upload(upload.name,upload.getvalue()); st.success(upload.name+' 저장 완료')
                except Exception as ex: st.error(str(ex))
            st.session_state.pop('loaded',None)
            st.rerun()
        st.code(str(RAW),language=None)
        st.caption('확인된 재고·반품·재고변동·재고손실보상·광고비 상세·광고 성과 엑셀은 Downloads에서도 자동으로 가져옵니다. 낯선 파일은 구조를 확인한 뒤 연결합니다.')
        st.link_button('정산·CFS 자료 열기','https://wing.coupang.com/tenants/rfm/settlements/home')
        st.link_button('광고비 내역 열기','https://wing.coupang.com/tenants/rfm-portal-2/cmg/settlement')
        st.link_button('광고 성과 보고서 열기','https://advertising.coupang.com/marketing-reporting/billboard/reports/pa')
        st.caption('새 광고 성과 파일: 기간 설정 → 일별 → 캠페인 > 광고그룹 > 상품 → 모든 캠페인 → 보고서 만들기 → 다운로드. 그 뒤 대시보드 새로고침으로 최신 파일을 자동 검증합니다.')
    with tabs[4]:
        terms=[('판매가능재고','지금 판매에 사용할 수 있다고 쿠팡이 표시한 재고입니다. 파일 생성 시점 기준입니다.'),
        ('예상 소진일 (DOC)','쿠팡의 판매 예측을 이용한 추정값입니다. 판매가 없는 상품의 70일 표기를 정확한 품절 날짜로 보지 않습니다.'),
        ('최근 매출','원본은 번들 판매를 제외합니다. 최근 7일/30일은 이번달과 다른 기간입니다.'),
        ('반품률','같은 주문 집단의 판매·반품 수량을 대조해야 합니다. 현재 반품 파일은 수량 열이 없어 확정 반품률을 계산하지 않습니다.'),
        ('90일 미회수','원본 안내에 따른 보상 검토 후보입니다. 지급 여부와 처리 상태를 대조해야 받을 돈을 확정할 수 있습니다.'),
        ('순이익','매출에서 원가·수수료·물류·광고·반품손실 등을 빼고 확정 보상금을 더한 금액입니다. 누락된 비용을 0원으로 보지 않습니다.'),
        ('새로고침','빠른 새로고침은 API 주문·재고·상품을 조회하고 저장된 파일을 다시 읽습니다. 화면·엑셀 원본 갱신은 Aside에서 화면과 엑셀 3종을 새로 수집합니다. 손익·반품 분석은 원본 파일의 생성시각 기준이며 쿠팡의 집계 지연은 남습니다.')]
        for term,explanation in terms: st.markdown(f'**{term}**  \n{explanation}')
    with tabs[5]:
        st.subheader('로그인된 Chrome과 연결')
        st.write('이 PC에 만든 수집기를 Chrome에 한 번 설치하면 새로고침 요청을 받아 윙 재고·정산·광고비·반품과 광고센터 이번달 화면을 읽고 재고·반품·광고 청구 상세 엑셀을 내려받습니다.')
        st.info('수집 결과와 새 파일 생성 시각을 확인하세요. 정산 상세 원본과 광고 성과 보고서의 자동 수집은 아직 연결되지 않았습니다.')
        st.markdown('1. Chrome에서 **확장 프로그램 관리**를 엽니다.\n2. **개발자 모드 → 압축해제된 확장 프로그램 로드**에서 아래 폴더를 선택합니다.\n3. 수집기 아이콘을 누르고 아래 연결 코드를 입력합니다.\n4. 쿠팡윙에 로그인한 상태에서 대시보드 **새로고침**을 누릅니다.')
        st.code(str(ROOT/'browser_extension'),language=None)
        if bridge:
            st.caption('연결 코드는 이 PC 브라우저와 대시보드 사이에서만 사용합니다. 서버 재시작 시 바뀝니다.')
            with st.expander('브라우저 연결 코드 표시'):
                st.code(bridge.token,language=None)
            state=bridge.status()
            st.write('연결 상태: '+('연결됨' if state['connected'] else '미연결'))
            st.write('수집 상태: '+state['status'])
        else: st.error('로컬 수집 서버 포트 8765를 열 수 없습니다. 이미 실행 중인 대시보드가 있는지 확인해 주세요.')
        st.caption('권한 범위: wing.coupang.com·advertising.coupang.com 화면 읽기, 허용된 엑셀 다운로드, 127.0.0.1 전송. 비밀번호·쿠키를 읽지 않습니다. 정산 상세·광고 성과의 전체 이력은 추가 검증이 필요합니다.')

@st.fragment(run_every='15s')
def watch_files():
    from src.file_loader import sync_downloads
    sync_downloads()
    watched=list(RAW.glob('*.xlsx'))+list((DATA/'evidence').glob('*.txt'))+[p for p in [DATA/'api_snapshot.json',DATA/'browser_snapshot.json'] if p.exists()]
    fingerprint=tuple(sorted((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in watched))
    previous=st.session_state.get('fingerprint')
    st.session_state['fingerprint']=fingerprint
    if previous is not None and previous!=fingerprint:
        st.session_state.pop('loaded',None); st.rerun()
    if bridge:
        state=bridge.status()
        st.caption('브라우저: '+('연결됨' if state['connected'] else '미연결')+' · '+state['status'])
watch_files()
st.caption('ROCKET DESK · 로컬 전용 · 자료의 수집시각과 누락 여부를 함께 확인하세요.')
