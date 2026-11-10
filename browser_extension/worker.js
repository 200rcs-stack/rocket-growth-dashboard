// All target URLs and allowed UI actions are fixed. No cookies/password access.
const BASE='http://127.0.0.1:8765';
const URLS={inventory:'https://wing.coupang.com/tenants/rfm-inventory/management/list',settlement:'https://wing.coupang.com/tenants/rfm/settlements/home',ad_billing:'https://wing.coupang.com/tenants/rfm-portal-2/cmg/settlement',customer_returns:'https://wing.coupang.com/tenants/rfm/c-return/main',ad_performance:'https://advertising.coupang.com/marketing/dashboard/sales'};
let busy=false;
chrome.runtime.onInstalled.addListener(()=>chrome.alarms.create('poll',{periodInMinutes:0.5}));
chrome.runtime.onStartup.addListener(()=>chrome.alarms.create('poll',{periodInMinutes:0.5}));
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='poll')poll();});
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
 if(message.type==='poll'){poll().finally(()=>sendResponse({ok:true}));return true;}
});
async function collectAdDashboard(job,registerTab){
 const started=new Date().toISOString();
 const candidates=await chrome.tabs.query({url:'https://advertising.coupang.com/*'});
 const source=candidates.find(t=>t.id&&t.title?.includes('Coupang Ads')&&!t.url.includes('/keycloak_callback'));
 const activeBefore=source?(await chrome.tabs.query({active:true,windowId:source.windowId}))[0]:null;
 let tab=source?await chrome.tabs.duplicate(source.id):null;
 if(tab)await chrome.tabs.update(tab.id,{url:job.url,active:true});
 else tab=await chrome.tabs.create({url:job.url,active:true});
 registerTab(tab.id);
 try{
  for(let i=0;i<60;i++){
   const state=await chrome.tabs.get(tab.id);
   if(state.status==='complete')break;
   await new Promise(r=>setTimeout(r,500));
  }
  const landed=await chrome.tabs.get(tab.id);
  if(!landed.url?.startsWith('https://advertising.coupang.com/marketing/'))
   return {kind:job.kind,url:job.url,captured_at:new Date().toISOString(),status:'광고센터 로그인 필요',text:'광고센터 성과 화면 대신 로그인 화면이 열렸습니다.'};
  const result=await chrome.scripting.executeScript({target:{tabId:tab.id},func:async()=>{
   const delay=ms=>new Promise(r=>setTimeout(r,ms));
   for(let i=0;i<60&&!document.body.innerText.includes('전체 성과 요약');i++)await delay(500);
   if(!document.body.innerText.includes('전체 성과 요약'))return {status:'로그인·화면 확인 필요',text:document.body.innerText.slice(0,1000)};
   const month=[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='이번달');
   if(!month)return {status:'기간 선택 확인 필요',text:'광고센터의 이번달 버튼을 찾지 못했습니다.'};
   month.click();
   let period='';
   for(let i=0;i<60;i++){
    period=[...document.querySelectorAll('button')].map(b=>b.innerText.trim()).find(t=>/^20\d{2}\.\d{2}\.\d{2}\s*~\s*20\d{2}\.\d{2}\.\d{2}$/.test(t))||'';
    if(period.startsWith(new Date().getFullYear()+'.'+String(new Date().getMonth()+1).padStart(2,'0')+'.01'))break;
    await delay(500);
   }
   let summary='';let spend=null;
   for(let i=0;i<60;i++){
    summary=document.body.innerText.split('전체 성과 요약',2)[1]?.split('성과 그래프',1)[0]||'';
    const match=summary.match(/전체 집행 광고비\s+([\d,]+)\s*원/);
    spend=match?Number(match[1].replaceAll(',','')):null;
    if(spend>0)break;
    await delay(500);
   }
   if(!period||!Number.isFinite(spend)||spend<=0||!['광고 전환 매출','광고 수익률'].every(t=>summary.includes(t)))
    return {status:'광고 성과 화면 확인 필요',text:('조회기간 '+period+'\n'+summary).slice(0,3000)};
   return {status:'수집 완료',text:'조회기간 '+period+'\n전체 성과 요약\n'+summary.slice(0,10000),note:'광고센터 이번달 화면 표시값입니다. 성과 엑셀과 청구 광고비는 별도 집계입니다.'};
  }});
  return {kind:job.kind,url:job.url,captured_at:new Date().toISOString(),...result[0].result};
 }catch(e){return {kind:job.kind,url:job.url,captured_at:started,status:'광고센터 로그인·권한 확인 필요',text:String(e.message).slice(0,300)};}
 finally{
  await chrome.tabs.remove(tab.id).catch(()=>{});
  if(activeBefore?.id)await chrome.tabs.update(activeBefore.id,{active:true}).catch(()=>{});
 }
}
async function collect(job,registerTab){
 if(URLS[job.kind]!==job.url)throw Error('허용되지 않은 수집 주소');
 if(job.kind==='ad_performance')return collectAdDashboard(job,registerTab);
 const started=new Date().toISOString();
 // Wing keeps some sign-in state per tab. Clone an already signed-in Wing tab
 // so a new background page inherits that state without reading credentials.
 const candidates=await chrome.tabs.query({url:'https://wing.coupang.com/*'});
 const signedIn=candidates.filter(t=>t.id&&t.title?.startsWith('Coupang Wing')&&t.url?.startsWith('https://wing.coupang.com/tenants/')
                                  &&!t.url.includes('/confirm-password')&&!t.url.includes('/excel/'));
 const source=(signedIn.filter(t=>Object.values(URLS).some(url=>t.url.startsWith(url)))
                        .sort((a,b)=>b.id-a.id)[0])||signedIn.sort((a,b)=>b.id-a.id)[0];
 const activeBefore=source?(await chrome.tabs.query({active:true,windowId:source.windowId}))[0]:null;
 let tab=source?await chrome.tabs.duplicate(source.id):null;
 // Keep the collection tab active until download actions finish. Wing fills
 // inventory rows asynchronously, and Chrome may defer downloads in a hidden tab.
 if(tab) await chrome.tabs.update(tab.id,{url:job.url,active:true});
 else tab=await chrome.tabs.create({url:job.url,active:true});
 registerTab(tab.id);
 try{
  let landed=false;
  for(let i=0;i<60;i++){
   const state=await chrome.tabs.get(tab.id);
   if(state.status==='complete'){
    landed=true;break;
   }
   await new Promise(r=>setTimeout(r,500));
  }
  if(!landed)return {kind:job.kind,url:job.url,captured_at:new Date().toISOString(),status:'화면 이동 시간 초과',text:'쿠팡윙 화면 로딩을 완료하지 못했습니다.'};
  const destination=await chrome.tabs.get(tab.id);
  if(!destination.url?.startsWith('https://wing.coupang.com/tenants/'))
   return {kind:job.kind,url:job.url,captured_at:new Date().toISOString(),status:'쿠팡윙 로그인 필요',text:'쿠팡윙 자료 화면 대신 로그인 화면이 열렸습니다.'};
  await new Promise(r=>setTimeout(r,1000));
  const scrape=async(kind,range)=>{
   const delay=ms=>new Promise(r=>setTimeout(r,ms));
   const visible=e=>e.getClientRects().length>0;
   for(let i=0;i<30;i++){
    if(document.querySelector('#wing-main-content')?.innerText.trim().length>50)break;
    if(document.querySelector('input[type="password"]'))return {status:'로그인 필요',text:'쿠팡윙 로그인이 필요합니다.'};
    await delay(500);
   }
   const main=document.querySelector('#wing-main-content');
   if(!main)return {status:'화면 확인 필요',text:'알려진 본문 영역을 찾지 못했습니다.'};
   if(/captcha|자동입력 방지|보안문자/i.test(main.innerText))return {status:'사용자 확인 필요',text:'쿠팡 보안 확인 화면입니다.'};
   const ready={inventory:t=>t.includes('재고현황')&&/[1-9][0-9]*개 상품중/.test(t)&&t.includes('상품정보')&&!t.includes('검색 결과가 없습니다.'),
                settlement:t=>t.includes('수익 현황')&&t.includes('판매수수료'),
                ad_billing:t=>t.includes('로켓그로스 광고비 요약')&&t.includes('청구 대상액'),
                customer_returns:t=>t.length>700&&t.includes('반품')}[kind];
   for(let i=0;i<60&&!ready(main.innerText);i++)await delay(500);
   if(!ready(main.innerText))return {status:'화면 본문 확인 필요',text:main.innerText.slice(0,1000)};
   if(kind==='settlement'&&range){
    const read=()=>{
     const text='수익 현황'+(main.innerText.split('수익 현황')[1]?.split('다가오는 정산')[0]||'');
     const m=text.match(/(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*~\s*(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})/);
     const date=i=>m[i]+'-'+m[i+1].padStart(2,'0')+'-'+m[i+2].padStart(2,'0');
     return m&&date(1)===range.start&&date(4)===range.end&&ready(text)&&!text.includes('시스템 오류')?text:null;
    };
    const fail=()=>({status:'Wing 조회기간 선택 확인 필요',text:''});
    if(!/^\d{4}-\d{2}-\d{2}$/.test(range.start)||!/^\d{4}-\d{2}-\d{2}$/.test(range.end))return fail();
    if(!read()){
     const picker=[...main.querySelectorAll('button.custom-selection')].find(visible);
     if(!picker)return fail();
     picker.click();
     for(const [index,day] of [range.start,range.end].entries()){
      const wanted=Number(day.slice(0,4))*12+Number(day.slice(5,7));let selected=false;
      for(let i=0;i<32;i++){
       await delay(80);
       const cell=[...document.querySelectorAll('.dp__calendar_item[id="'+day+'"]:not([aria-disabled="true"]) .dp__cell_inner:not(.dp__cell_offset)')].find(visible);
       if(cell){cell.click();selected=true;break;}
       const label=[...document.querySelectorAll('.custom-month-year-information')].find(visible)?.innerText.match(/(20\d{2})년\s*(\d{1,2})월/);
       if(!label)return fail();
       const first=Number(label[1])*12+Number(label[2]),direction=wanted<first?'left':wanted>first+1?'right':'';
       if(!direction)return fail();
       const buttons=[...document.querySelectorAll('.custom-month-year-controller i[title="arrow-'+direction+'"]')].filter(visible);
       const nav=direction==='left'?buttons[0]:buttons.at(-1);
       if(!nav)return fail();nav.click();
      }
      if(!selected)return fail();
      const mark=index===0?'dp__range_start':'dp__range_end';
      const marker='.dp__calendar_item[id="'+day+'"] .'+mark;
      for(let i=0;i<12&&!document.querySelector(marker);i++)await delay(120);
      if(!document.querySelector(marker)&&!(index===1&&range.start===range.end))return fail();
     }
     const done=[...document.querySelectorAll('button')].find(e=>visible(e)&&e.innerText.trim()==='완료'&&!e.disabled);
     if(!done)return fail();done.click();await delay(1300);
    }
    let previous=null;
    for(let i=0;i<20;i++){
     const text=read();
     if(text&&text===previous)return {status:'수집 완료',text,note:'Chrome · 선택한 Wing 조회기간 확인'};
     previous=text;await delay(500);
    }
    return fail();
   }
   if(kind==='settlement'){
    const all=[...main.querySelectorAll('button,span,div,a')].filter(e=>visible(e)&&e.innerText.trim()==='이번 달');
    const month=all.find(e=>!all.some(child=>child!==e&&e.contains(child)));
    if(month){month.click();await delay(1200);}
    for(let i=0;i<30;i++){
     if(/20\d{2}\.\s*\d{1,2}\.\s*1\s*~/.test(main.innerText))break;
     await delay(500);
    }
   }
   const captured=main.innerText.slice(0,250000);
   const downloads=[];
   if(kind==='inventory'){
    const clickExact=(selector,text)=>{const matched=[...main.querySelectorAll(selector)].filter(e=>visible(e)&&e.innerText.trim()===text);const found=matched.filter(e=>!matched.some(other=>other!==e&&e.contains(other)));if(found.length===1){found[0].click();return true;}return false;};
    const menu=[...main.querySelectorAll('button')].find(e=>visible(e)&&e.innerText.trim()==='엑셀 다운로드');
    if(menu){
     menu.click();await delay(300);
     if(clickExact('span,div,li,a','엑셀 다운로드 요청'))downloads.push('재고 엑셀 요청 클릭');
     else downloads.push('재고 다운로드 메뉴 수동 확인 필요');
    }else downloads.push('다운로드 버튼 수동 확인 필요');
   }
   return {status:captured.includes('시스템 오류로 데이터를 표기할 수 없습니다')?'쿠팡 시스템 오류':'수집 완료',text:captured,downloads,
           note:'현재 화면의 표시 범위입니다. 페이지 전체 이력 수집과 다운로드 완료를 의미하지 않습니다.'};
  };
  let results;
  for(let i=0;i<30;i++){
   try{
    results=await chrome.scripting.executeScript({target:{tabId:tab.id},func:scrape,args:[job.kind,job.range||null]});
    break;
   }catch(e){
    if(!/Cannot access contents|permission to access|cannot be scripted/i.test(String(e.message)))throw e;
    await new Promise(r=>setTimeout(r,500));
   }
  }
  if(!results)return {kind:job.kind,url:job.url,captured_at:new Date().toISOString(),status:'로그인·권한 확인 필요',text:'새 탭이 쿠팡윙 화면으로 열리지 않았습니다. 같은 Chrome 프로필에서 윙에 다시 로그인해 주세요.'};
  const result={kind:job.kind,url:job.url,captured_at:new Date().toISOString(),...results[0].result};
  if(result.status==='수집 완료'&&(job.kind==='inventory'||job.kind==='ad_billing')){
   // Wing opens these exports with window.open. A background script click has
   // no transient user gesture, so capture Wing's own URL in MAIN world and
   // let the already-authorized downloads API fetch the same file.
   const captured=await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',args:[job.kind],func:async kind=>{
    const delay=ms=>new Promise(r=>setTimeout(r,ms));
    const main=document.querySelector('#wing-main-content');
    if(!main)return null;
    const original=window.open;
    let opened=null;
    window.open=function(url,...rest){
     const value=String(url||'');
     if(value.startsWith('/tenants/rfm-inventory/excel/v2/skureturns/')||value.startsWith('/tenants/rfm-portal-2/excel/cmg-settlement/')){opened=value;return null;}
     return original.call(this,url,...rest);
    };
    try{
     if(kind==='ad_billing'){
      const button=main.querySelector('#excel-download-btn');
      if(button)button.click();
     }else{
      // The stock-export click above may leave the menu open. Clicking its
      // toggle again would close it, and Wing can render the popup in a portal
      // outside #wing-main-content.
      const findReturn=()=>{
       const matches=[...document.querySelectorAll('button,span,div,li,a')]
        .filter(e=>e.getClientRects().length&&e.innerText.trim()==='반품내역 엑셀 다운로드');
       return matches.find(e=>!matches.some(other=>other!==e&&e.contains(other)));
      };
      let leaf=findReturn();
      if(!leaf){
       const menu=[...main.querySelectorAll('button')].find(e=>e.innerText.trim()==='엑셀 다운로드');
       if(menu)menu.click();
       for(let i=0;i<15&&!leaf;i++){await delay(100);leaf=findReturn();}
      }
      if(leaf)leaf.click();
     }
     for(let i=0;i<50&&!opened;i++)await delay(100);
     return opened;
    }finally{window.open=original;}
   }});
   const path=captured?.[0]?.result;
   const valid=job.kind==='ad_billing'
    ? /^\/tenants\/rfm-portal-2\/excel\/cmg-settlement\/\d{4}\/(?:[1-9]|1[0-2])$/.test(path||'')
    : /^\/tenants\/rfm-inventory\/excel\/v2\/skureturns\/[A-Z]\d+\/\d{13}\/\d{13}$/.test(path||'');
   if(valid){
    await chrome.downloads.download({url:'https://wing.coupang.com'+path,conflictAction:'uniquify',saveAs:false});
    result.downloads.push(job.kind==='ad_billing'?'광고 상세 엑셀 클릭':'반품 엑셀 요청 클릭');
   }else result.downloads.push(job.kind==='ad_billing'?'광고 상세 파일 주소 확인 필요':'반품 파일 주소 확인 필요');
  }
  if(result.downloads?.some(x=>x.includes('요청 클릭')||x.includes('광고 상세 엑셀 클릭'))){
   const wanted=[];
   if(result.downloads.includes('재고 엑셀 요청 클릭'))wanted.push('inventory_health_sku_info_');
   if(result.downloads.includes('반품 엑셀 요청 클릭'))wanted.push('inventory_health_creturn_v2_info_');
   if(result.downloads.includes('광고 상세 엑셀 클릭'))wanted.push('cmg_settlement_detail_');
   let completed=[];
   for(let i=0;i<45;i++){
    completed=[];
    for(const prefix of wanted){
     const matches=await chrome.downloads.search({startedAfter:started,state:'complete',limit:100});
     completed.push(...matches.filter(d=>d.filename.split(/[\\/]/).pop().startsWith(prefix)).map(d=>({name:d.filename.split(/[\\/]/).pop(),state:d.state})));
    }
    if(wanted.every(prefix=>completed.some(d=>d.name.startsWith(prefix))))break;
    await new Promise(r=>setTimeout(r,1000));
   }
   result.completed_files=completed;
   if(!wanted.every(prefix=>completed.some(d=>d.name.startsWith(prefix))))result.status='화면 수집 완료 · 파일 다운로드 확인 필요';
  }else if(job.kind==='inventory'&&result.status==='수집 완료')result.status='화면 수집 완료 · 파일 다운로드 미실행';
  if(result.status==='수집 완료'&&result.downloads?.some(x=>x.includes('확인 필요')))result.status='화면 수집 완료 · 파일 다운로드 확인 필요';
  return result;
 }finally{
  await chrome.tabs.remove(tab.id).catch(()=>{});
  if(activeBefore?.id)await chrome.tabs.update(activeBefore.id,{active:true}).catch(()=>{});
 }
}
async function collectBounded(item){
 let ownedTab=null,timer,timedOut=false;
 const timeout={kind:item.kind,url:item.url,status:'화면 수집 시간 초과',text:'이 화면이 70초 안에 끝나지 않아 다음 화면으로 넘어갔습니다.',captured_at:new Date().toISOString()};
 const attempt=collect(item,id=>{ownedTab=id;if(timedOut)chrome.tabs.remove(id).catch(()=>{});});
 try{
  const result=await Promise.race([attempt,new Promise(resolve=>{timer=setTimeout(()=>{timedOut=true;resolve(timeout);},70000);})]);
  if(result===timeout&&ownedTab)await chrome.tabs.remove(ownedTab).catch(()=>{});
  return result;
 }finally{clearTimeout(timer);}
}
async function poll(){
 if(busy)return;busy=true;
 try{
  const config=await chrome.storage.local.get(['token','enabled']);if(!config.enabled||!config.token)return;
  const headers={'Authorization':'Bearer '+config.token,'Content-Type':'application/json','X-Rocket-Settlement-Range':'1'};
  const r=await fetch(BASE+'/job',{headers});if(!r.ok)return;
  const job=await r.json();if(!job.id)return;
  const sources=[];
  for(const item of job.jobs){
   try{sources.push(await collectBounded(item));}
   catch(e){sources.push({kind:item.kind,url:item.url,status:'수집 실패',text:String(e.message).slice(0,300),captured_at:new Date().toISOString()});}
  }
  await fetch(BASE+'/result',{method:'POST',headers,body:JSON.stringify({id:job.id,sources})});
 }catch(e){/* Offline app: keep user session and wait for next alarm. */}
 finally{busy=false;}
}
