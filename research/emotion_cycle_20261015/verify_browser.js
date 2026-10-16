async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 if(!await page.locator('#fresh-txt').innerText().then(t=>t.includes('情绪 · 正式收盘已核验')))throw Error('Emotion source clock header missing');
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,source:DATA.emotion_relay.source_at,version:DATA.emotion_relay.version,hash:DATA.emotion_relay.implementation_hash,maHash:DATA.ma_trend.implementation_hash,cycle:DATA.emotion_relay.cycles.cycle_highest,days:DATA.emotion_relay.timeline.map(t=>t.date),lists:Object.fromEntries(Object.entries(DATA.emotion_relay.lists).map(([k,v])=>[k,v.length]))}));
 if(base.maHash!=='e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261'||base.cycle!==10||base.days.length!==20||new Set(base.days).size!==20)throw Error('MA/cycle/calendar mismatch');
 const scope=page.getByRole('combobox',{name:'接力观察范围',exact:true});
 for(const value of ['all','leaders','continuation','companions','suspended','sealed','broken','pending']){
  await scope.selectOption(value);const n=await page.locator('#emotion-host [data-relay-code]').count();
  if(n!==Math.min(base.lists[value],100))throw Error('Scope mismatch '+value+' '+n+'/'+base.lists[value]);
 }
 await scope.selectOption('all');await page.screenshot({path:'output/playwright/emotion-cycle-overview.png',fullPage:false});
 await scope.selectOption('suspended');const paused=page.locator('#emotion-host [data-relay-code="600825"]');
 if(!await paused.innerText().then(t=>t.includes('10板 · 停牌保留')&&t.includes('2026-10-12')&&t.includes('13.78')))throw Error('Paused core last real trade missing');
 await paused.locator('[data-tip]').first().hover();const tip=await page.getByRole('tooltip').innerText();if(!tip.includes('停牌'))throw Error('Pause tooltip missing');await page.mouse.move(12,12);
 await paused.click();await page.locator('.er-stock-detail').waitFor();await page.locator('.er-stock-detail > summary').click();
 const pausedDetail=await page.locator('.er-stock-detail').innerText();if(!pausedDetail.includes('全天停牌')||!pausedDetail.includes('股票交易风险提示暨停牌核查公告'))throw Error('Disclosure/history detail missing');
 const historyRows=await page.locator('.er-stock-detail table tbody tr').count();if(historyRows!==20)throw Error('Detail missing full 20 sessions');
 await page.screenshot({path:'output/playwright/emotion-cycle-paused-detail.png',fullPage:false});await page.locator('#dr-x').click();
 await scope.selectOption('continuation');const cw=page.locator('#emotion-host [data-relay-code="002343"]');
 if(!await cw.innerText().then(t=>t.includes('监管接续候选')&&t.includes('2026-10-09')))throw Error('CW regulatory node missing');
 await cw.click();await page.locator('.er-stock-detail').waitFor();await page.locator('.er-stock-detail > summary').click();
 const cwDetail=await page.locator('.er-stock-detail').innerText();if(!cwDetail.includes('2026-10-08 21:20:02')||!cwDetail.includes('sz399107')||!cwDetail.includes('不作为正式异动认定'))throw Error('Node publication or deviation basis missing');await page.locator('#dr-x').click();
 const api=await page.evaluate(async()=>{
  const version=DATA.ui_generation;const detail=await fetch('/__ui/detail?version='+version+'&kind=stock&id=002343').then(r=>r.json());
  const csv=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes:erRows().map(r=>r.code),contexts:{view:'emotion'}})}).then(async r=>{if(!r.ok)throw Error('CSV '+r.status);return r.text()});
  if(detail.version!==version||!csv.includes(version)||!csv.includes(DATA.emotion_relay.implementation_hash)||!csv.includes('异动披露与参考')||!csv.includes('监管接续候选'))throw Error('CSV/detail mismatch');
  let timeline='';const old=downloadMSCSV;try{downloadMSCSV=x=>timeline=x;erTimelineCSV();}finally{downloadMSCSV=old;}if(timeline.trim().split('\n').length!==21||!timeline.includes(version))throw Error('20-day CSV mismatch');
  return {version,rows:csv.trim().split('\n').length-1,timelineRows:20};
 });
 await scope.selectOption('all');
 const composition=await page.evaluate(async()=>{
  const input=document.querySelector('[aria-label="情绪股票搜索"]');input.focus();input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));input.value='慈文';input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'慈文'}));renderEmotion();
  const kept=document.activeElement===input&&document.querySelector('[aria-label="情绪股票搜索"]')===input;
  input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'慈文'}));input.dispatchEvent(new InputEvent('input',{bubbles:true,data:'慈文'}));await new Promise(r=>setTimeout(r,120));return {kept,q:MS_VIEW.emotion.q,ids:erRows().map(r=>r.code)};
 });if(!composition.kept||composition.q!=='慈文'||!composition.ids.includes('002343'))throw Error('IME failed');
 await page.getByRole('textbox',{name:'情绪股票搜索',exact:true}).fill('');
 await page.locator('#seg').getByRole('button',{name:'板块／题材',exact:true}).click();await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('theme');await page.getByRole('textbox',{name:'板块题材搜索',exact:true}).fill('文化传媒');
 await page.locator('#board-center [data-direction-id]').first().getByRole('button',{name:'完整成员排名',exact:true}).click();
 const ranks=await page.evaluate(()=>({expected:msRankContext().ranking.expected,actual:msRankRows().length,scope:MS_VIEW.stocks.scope}));if(ranks.expected!==124||ranks.actual!==124||ranks.scope!=='all')throw Error('Full direction members changed');
 await page.getByRole('combobox',{name:'个股排名方式',exact:true}).selectOption('emotion');
 const sorted=await page.evaluate(()=>msRankRows().map(r=>r.code));const expected=await page.evaluate(()=>msRankContext().ranking.emotion);if(JSON.stringify(sorted)!==JSON.stringify(expected))throw Error('Rank order differs from backend');
 const options=await page.getByRole('combobox',{name:'个股标签',exact:true}).locator('option').allTextContents();if(!options.includes('监管接续候选')||options.includes('同题材接续候选'))throw Error('Old tag selector remains');
 await page.getByRole('button',{name:'情绪',exact:true}).click();await scope.selectOption('continuation');await page.screenshot({path:'output/playwright/emotion-cycle-candidates.png',fullPage:false});
 const colors=await page.locator('#emotion-host .up,#emotion-host .down').evaluateAll(els=>Object.fromEntries(['up','down'].map(k=>{const el=els.find(e=>e.classList.contains(k));return [k,el?getComputedStyle(el).color:null]})));
 await page.setViewportSize({width:850,height:1000});await page.screenshot({path:'output/playwright/emotion-cycle-narrow.png',fullPage:false});await page.setViewportSize({width:1440,height:1000});
 const status=await page.evaluate(()=>fetch('/__status').then(r=>r.json()));if(status.phase!=='ready'||status.code_emotion_relay_hash!==base.hash||status.snapshot_emotion_relay_hash!==base.hash)throw Error('Service code/snapshot mismatch');
 if(errors.length)throw Error(errors.join(' | '));return {base,pausedDetail:true,historyRows,regulatoryDetail:true,tip,api,composition,ranks,colors,errors,pid:status.pid};
}
