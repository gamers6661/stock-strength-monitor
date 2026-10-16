async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,source:DATA.emotion_relay.source_at,version:DATA.emotion_relay.version,hash:DATA.emotion_relay.implementation_hash,maHash:DATA.ma_trend.implementation_hash,lists:Object.fromEntries(Object.entries(DATA.emotion_relay.lists).map(([k,v])=>[k,v.length])),closed:DATA.emotion_relay.highest_previous,live:DATA.emotion_relay.highest_live,expected:DATA.emotion_relay.coverage.expected_pool_days,verified:DATA.emotion_relay.coverage.verified_pool_days,rankFreshnessSeparated:typeof msRankStyleTags==='function'}));
 if(base.maHash!=='e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261')throw Error('MA implementation changed');
 const scope=page.getByRole('combobox',{name:'接力观察范围',exact:true});
 for(const value of ['all','leaders','continuation','sealed','broken','pending']){
  await scope.selectOption(value);
  const actual=await page.locator('#emotion-host [data-relay-code]').count();
  if(actual!==Math.min(base.lists[value],100))throw Error('Scope '+value+' differs from backend: '+actual+'/'+base.lists[value]);
 }
 await scope.selectOption('all');
 await page.screenshot({path:'output/playwright/emotion-relay-overview.png',fullPage:false});
 const composition=await page.evaluate(async()=>{
  const input=document.querySelector('[aria-label="情绪股票搜索"]');input.focus();input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:''}));input.value='百洋';input.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'百洋'}));renderEmotion();
  const kept=document.activeElement===input&&document.querySelector('[aria-label="情绪股票搜索"]')===input;
  input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'百洋'}));input.dispatchEvent(new InputEvent('input',{bubbles:true,data:'百洋'}));await new Promise(r=>setTimeout(r,120));
  return {kept,value:MS_VIEW.emotion.q,ids:erRows().map(r=>r.code)};
 });
 if(!composition.kept||composition.value!=='百洋'||!composition.ids.length)throw Error('IME composition lost');
 await page.getByRole('textbox',{name:'情绪股票搜索',exact:true}).fill('');
 await scope.selectOption('continuation');
 const first=page.locator('#emotion-host [data-relay-code]').first();const code=await first.getAttribute('data-relay-code');
 await first.locator('[data-tip]').first().hover();const tip=await page.getByRole('tooltip').innerText();
 if(!tip.includes('源行情')||tip.includes('后端状态'))throw Error('Missing relay explanation');
 await page.mouse.move(12,12);await first.scrollIntoViewIfNeeded();
 await page.screenshot({path:'output/playwright/emotion-relay-candidates.png',fullPage:false});
 const api=await page.evaluate(async code=>{
  const version=DATA.ui_generation;
  const detail=await fetch('/__ui/detail?version='+version+'&kind=stock&id='+code).then(r=>r.json());
  const csv=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes:erRows().map(r=>r.code),contexts:{view:'emotion',rankBoardId:'all'}})}).then(async r=>{if(!r.ok)throw Error('CSV '+r.status);return r.text()});
  if(detail.version!==version||!csv.includes(version)||!csv.includes(DATA.emotion_relay.implementation_hash)||!csv.includes('接力角色'))throw Error('CSV/detail generation mismatch');
  return {detailVersion:detail.version,csvRows:csv.trim().split('\n').length-1,candidate:code,continuation:detail.item.emotion_relay.continuation.length};
 },code);
 await first.click();await page.locator('.er-stock-detail').waitFor();await page.locator('.er-stock-detail > summary').click();
 const detailText=await page.locator('.er-stock-detail').innerText();if(!detailText.includes('主板龙头接力依据')||!detailText.includes('同题材核心'))throw Error('Relay detail missing');
 await page.locator('#dr-x').click();
 await page.getByRole('button',{name:'板块／题材',exact:true}).click();
 await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('all');
 const directions=await page.evaluate(()=>({all:erBoardRows().length,official:msBoardCatalog().length}));
 if(directions.all!==directions.official)throw Error('Merged directions omitted official members');
 await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('industry');
 const industry=await page.evaluate(()=>erBoardRows().every(b=>b.type==='industry'));if(!industry)throw Error('Industry kind broken');
 await page.getByRole('combobox',{name:'方向类型',exact:true}).selectOption('theme');
 const theme=await page.evaluate(()=>erBoardRows().every(b=>b.type==='theme'));if(!theme)throw Error('Theme kind broken');
 await page.getByRole('textbox',{name:'板块题材搜索',exact:true}).fill('文化传媒');
 await page.screenshot({path:'output/playwright/emotion-merged-directions.png',fullPage:false});
 const direction=await page.evaluate(async()=>{
  const b=erBoardRows()[0];if(!b)throw Error('Search omitted known official direction');
  const csv=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:DATA.ui_generation,kind:'board',ids:[b.id]})}).then(async r=>{if(!r.ok)throw Error('Direction CSV '+r.status);return r.text()});
  if(!csv.includes('当前在板数')||!csv.includes(DATA.ui_generation))throw Error('Direction CSV mismatch');
  return {id:b.id,members:b.member_codes.length,csvRows:csv.trim().split('\n').length-1};
 });
 await page.locator('#board-center [data-direction-id]').first().getByRole('button',{name:'完整成员排名',exact:true}).click();
 const ranks=await page.evaluate(()=>({expected:msRankContext().ranking.expected,actual:msRankRows().length,scope:MS_VIEW.stocks.scope,roles:msRankContext().ranking.emotion_valid}));
 if(ranks.expected!==direction.members||ranks.actual!==direction.members||ranks.scope!=='all')throw Error('Full member ranking incomplete');
 await page.getByRole('combobox',{name:'个股排名方式',exact:true}).selectOption('emotion');
 const sorted=await page.evaluate(()=>msRankRows().map(r=>r.code));
 const expected=await page.evaluate(()=>msRankContext().ranking.emotion);
 if(JSON.stringify(sorted)!==JSON.stringify(expected))throw Error('Relay ranking differs from backend');
 await page.screenshot({path:'output/playwright/emotion-member-ranking.png',fullPage:false});
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 await scope.selectOption('all');
 const colors=await page.locator('#emotion-host .up,#emotion-host .down').evaluateAll(els=>Object.fromEntries(['up','down'].map(k=>{const el=els.find(e=>e.classList.contains(k));return [k,el?getComputedStyle(el).color:null]})));
 if(errors.length)throw Error(errors.join(' | '));
 return {base,composition,tip,api,directions,direction,ranks,colors,detailChecked:!!detailText,errors};
}
