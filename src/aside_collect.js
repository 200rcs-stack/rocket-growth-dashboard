// Executed by the installed Aside CLI in its own browser REPL session.
// Only rendered page text crosses into the local dashboard. Vault secrets do not.
const urls = {
  inventory: 'https://wing.coupang.com/tenants/rfm-inventory/management/list',
  settlement: 'https://wing.coupang.com/tenants/rfm/settlements/home',
  ad_billing: 'https://wing.coupang.com/tenants/rfm-portal-2/cmg/settlement',
  customer_returns: 'https://wing.coupang.com/tenants/rfm/c-return/main',
  ad_performance: 'https://advertising.coupang.com/marketing/dashboard/sales',
};
const sources = [];
let wing = selectedKinds.includes('inventory') ? await openTab(urls.inventory) : null;
function isStale(error) {
  return /RefStaleError|is stale/i.test(String(error));
}
async function clickFresh(tab, match, state) {
  for (let n = 0; n < 2; n++) {
    const ref = (state ?? await snapshot(tab, {interactive: true})).tree.match(match)?.[1];
    if (!ref) return false;
    try {
      await tab.locator(ref).click();
      return true;
    } catch (error) {
      if (!isStale(error) || n === 1) throw error;
      state = null;
    }
  }
  return false;
}
function wingPeriod(text) {
  const section=text.split('수익 현황')[1]?.split('다가오는 정산')[0]||'';
  const m=section.match(/(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*~\s*(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})/);
  const date=(i)=>m[i]+'-'+m[i+1].padStart(2,'0')+'-'+m[i+2].padStart(2,'0');
  return m ? {start:date(1),end:date(4)} : null;
}
async function selectWingRange(tab, range) {
  await tab.locator('button.custom-selection').click();
  for (const [index,day] of [range.start,range.end].entries()) {
    const target=Number(day.slice(0,4))*12+Number(day.slice(5,7));
    for(let i=0;i<32;i++){
      const cell=tab.locator('.dp__calendar_item[id="'+day+'"]:not([aria-disabled="true"]) .dp__cell_inner:not(.dp__cell_offset)');
      if(await cell.count()===1){await cell.click();break;}
      const text=await tab.locator('.custom-month-year-information').first().innerText();
      const shown=text.match(/(20\d{2})년\s*(\d{1,2})월/);
      if(!shown||i===31)throw Error('Unable to select date');
      const first=Number(shown[1])*12+Number(shown[2]);
      const direction=target<first?'left':target>first+1?'right':'';
      if(!direction)throw Error('Unavailable date');
      const nav=tab.locator('.custom-month-year-controller i[title="arrow-'+direction+'"]:visible');
      await (direction==='left'?nav.first():nav.last()).click();
    }
    const mark=index===0?'dp__range_start':'dp__range_end';
    const selected=tab.locator('.dp__calendar_item[id="'+day+'"] .'+mark);
    for(let i=0;i<12&&!(await selected.count());i++)await sleep(120);
    if(!(await selected.count())&&!(index===1&&range.start===range.end))throw Error('Unconfirmed date selection');
  }
  if(!await clickFresh(tab,/button "완료" \[ref=([^\]]+)\]/))throw Error('Unable to apply dates');
}
async function wingText(tab, kind) {
  const checks = {
    inventory: text => /[1-9][0-9]*개 상품중/.test(text) && text.includes('상품정보') && text.length > 2500,
    settlement: text => text.includes('수익 현황') && text.includes('판매수수료'),
    ad_billing: text => text.includes('로켓그로스 광고비 요약') && text.includes('청구 대상액'),
    customer_returns: text => text.includes('반품') && text.length > 700,
  };
  let text = '';
  let savedLoginAttempted = false;
  let loginSuggestionsOpened = false;
  let xauthCount = 0;
  let blankBody = false;
  let reloaded = false;
  let monthRequested = false;
  let rangeRequested = false;
  let rangeFailed = false;
  const range=kind==='settlement'?settlementRange:null;
  const started = Date.now();
  for (let n = 0; n < 100 && Date.now()-started < 65000; n++) {
    const current = await snapshot(tab, {interactive: true});
    // The redirect to xauth can arrive after openTab's first snapshot. Handle
    // that delayed redirect here, using only the browser's saved-login button.
    if (tab.url().startsWith('https://xauth.coupang.com/')) {
      xauthCount++;
      if (current.tree.includes('Cookie not found') || xauthCount > 2) break;
      const saved = /button "Fill saved login coupang\.com, rcs20000" \[ref=([^\]]+)\]/;
      try {
        if (!savedLoginAttempted && saved.test(current.tree)) {
          savedLoginAttempted = await clickFresh(tab, saved, current);
        } else if (!loginSuggestionsOpened && !savedLoginAttempted) {
          loginSuggestionsOpened = await clickFresh(tab, /textbox "아이디를 입력해주세요" \[ref=([^\]]+)\]/, current);
        } else {
          break;
        }
      } catch (error) {
        if (!isStale(error)) throw error;
      }
      await sleep(400);
      continue;
    }
    if (!tab.url().startsWith('https://wing.coupang.com/tenants/')) break;
    try { text = await tab.locator('#wing-main-content').innerText(); } catch { break; }
    if (checks[kind](text)) {
      if(range){
        const actual=wingPeriod(text);
        if(actual?.start===range.start&&actual?.end===range.end)break;
        if(!rangeRequested){
          rangeRequested=true;
          try{await selectWingRange(tab,range);await sleep(1300);}catch{rangeFailed=true;break;}
        }
        await sleep(500);
        continue;
      }
      if (kind === 'settlement' && !monthRequested) {
        if (await clickFresh(tab, /button "이번 달" \[ref=([^\]]+)\]/, current)) {
          await snapshot(tab, {interactive: true});
          monthRequested = true;
          continue;
        }
      }
      break;
    }
    // Both rfm pages can render only the common footer when their JS fails.
    // This is not an expired login and must not prompt repeated authentication.
    if (['settlement','customer_returns'].includes(kind) && text.includes('페이지 별점을 주세요!') && text.length < 400) {
      if (!reloaded && Date.now()-started > 30000) { await tab.reload(); reloaded = true; continue; }
      if (Date.now()-started > 60000) { blankBody = true; break; }
    }
    // The Wing shell appears before its business app. Snapshot counts are not
    // a clock: allow the observed loading state time to resolve.
    await sleep(500);
  }
  return {
    kind, url: urls[kind], captured_at: new Date().toISOString(),
    status: rangeFailed || (range && checks[kind](text) &&
       (wingPeriod(text)?.start!==range.start||wingPeriod(text)?.end!==range.end)) ? 'Wing 조회기간 선택 확인 필요' :
      checks[kind](text) ? '수집 완료' : blankBody ? '쿠팡윙 본문 로딩 실패' :
      tab.url().startsWith('https://wing.coupang.com/tenants/') ? '화면 본문 확인 필요' : '쿠팡윙 로그인 필요',
    text: text.slice(0, 250000), note: 'Aside 브라우저의 현재 화면 표시값',
  };
}
async function downloadFile(tab, filenamePrefix, trigger) {
  try {
    const state = await snapshot(tab, {interactive: true});
    const match = state.tree.match(trigger);
    if (!match) return {status: '다운로드 버튼 확인 필요'};
    const pending = tab.waitForEvent('download', {timeout: 15000});
    await tab.locator(match[1]).click();
    const download = await pending;
    const name = download.suggestedFilename();
    if (!name.startsWith(filenamePrefix) || !name.endsWith('.xlsx')) {
      return {status: '파일명 확인 필요', name};
    }
    const file = await download.path();
    const size = (await fs.stat(file)).size;
    return size > 1000 ? {status: '파일 저장 완료', name, file, size} : {status: '파일 내용 확인 필요', name, file, size};
  } catch (error) {
    return {status: '다운로드 실패', reason: String(error).slice(0, 300)};
  }
}
async function inventoryDownloads(tab) {
  const results = [];
  for (const [prefix, trigger] of [
    ['inventory_health_sku_info_', /generic "엑셀 다운로드 요청" \[ref=([^\]]+)\]/],
    ['inventory_health_creturn_v2_info_', /generic "반품내역 엑셀 다운로드" \[ref=([^\]]+)\]/],
  ]) {
    const menu = /button "엑셀 다운로드[^\"]*" \[ref=([^\]]+)\]/;
    if (!await clickFresh(tab, menu)) { results.push({status: '다운로드 메뉴 확인 필요', prefix}); continue; }
    results.push({prefix, ...(await downloadFile(tab, prefix, trigger))});
  }
  return results;
}
if (wing) {
const inventory = await wingText(wing, 'inventory');
if (inventory.status === '수집 완료') inventory.downloads = await inventoryDownloads(wing);
sources.push(inventory);
}
for (const kind of ['settlement', 'ad_billing', 'customer_returns'].filter(kind => selectedKinds.includes(kind))) {
  const tab = await openTab(urls[kind]);
  const source = await wingText(tab, kind);
  if (kind === 'ad_billing' && source.status === '수집 완료') {
    source.downloads = [await downloadFile(tab, 'cmg_settlement_detail_', /button "[^\"]*엑셀 다운로드" \[ref=([^\]]+)\]/)];
  }
  sources.push(source);
  await closeTab(tab);
}
if (selectedKinds.includes('ad_performance')) {
let ad = await openTab(urls.ad_performance);
let adState = await snapshot(ad, {interactive: true});
if (ad.url().startsWith('https://advertising.coupang.com/user/login')) {
  const login = adState.tree.match(/link "로그인하기" \[ref=([^\]]+)\]/);
  if (login) {
    try { await ad.locator(login[1]).click(); } catch {}
  }
}
for (let n = 0; n < 12; n++) {
  adState = await snapshot(ad, {interactive: true});
  if (adState.tree.includes('button "이번달"')) break;
}
const close = adState.tree.match(/button "Close" \[ref=([^\]]+)\]/);
if (close) {
  try { await ad.locator(close[1]).click(); adState = await snapshot(ad, {interactive: true}); } catch {}
}
const month = adState.tree.match(/button "이번달" \[ref=([^\]]+)\]/);
if (month) {
  try { await ad.locator(month[1]).click(); adState = await snapshot(ad, {interactive: true}); } catch {}
}
let body = '';
const monthPrefix = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit'}).format(new Date()).replace('-', '.') + '.01';
for (let n = 0; n < 20; n++) {
  await snapshot(ad, {interactive: true});
  try { body = await ad.locator('body').innerText(); } catch { break; }
  const period = body.match(/20\d{2}\.\d{2}\.\d{2}\s*~\s*20\d{2}\.\d{2}\.\d{2}/)?.[0] || '';
  const summary = body.split('전체 성과 요약')[1]?.split('성과 그래프')[0] || '';
  if (period.startsWith(monthPrefix) && /전체 집행 광고비\s+[1-9][\d,]*\s+원/.test(summary) && summary.includes('광고 수익률')) break;
}
const period = body.match(/20\d{2}\.\d{2}\.\d{2}\s*~\s*20\d{2}\.\d{2}\.\d{2}/)?.[0] || '';
const summary = body.split('전체 성과 요약')[1]?.split('성과 그래프')[0] || '';
const adLoginRequired = ad.url().startsWith('https://advertising.coupang.com/user/login') ||
  ad.url().startsWith('https://xauth.coupang.com/');
sources.push({
  kind: 'ad_performance', url: urls.ad_performance, captured_at: new Date().toISOString(),
  status: adLoginRequired ? '광고센터 로그인 필요' :
    period.startsWith(monthPrefix) && /전체 집행 광고비\s+[1-9][\d,]*\s+원/.test(summary) && summary.includes('광고 수익률') ? '수집 완료' : '광고센터 이번달 화면 확인 필요',
  text: '조회기간 ' + period + '\n전체 성과 요약\n' + summary.slice(0, 10000),
  note: 'Aside 브라우저 광고센터 이번달 화면 표시값',
});
await closeTab(ad);
}
if (wing) await closeTab(wing);
// Python captures this private payload and validates the source and files.
console.log('ASIDE_RESULT_JSON=' + JSON.stringify({id: 'aside-' + Date.now(), received_at: new Date().toISOString(), sources}));
