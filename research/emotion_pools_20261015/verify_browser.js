async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,version:DATA.emotion_relay.version,hash:DATA.emotion_relay.implementation_hash,
   ma:DATA.ma_trend.implementation_hash,source:DATA.emotion_relay.source_at,pools:DATA.emotion_relay.pools,
   caps:DATA.emotion_relay.lists.sealed,broken:DATA.emotion_relay.lists.broken,promotion:DATA.emotion_relay.promotion}));
 if(base.version!=='mainboard-relay-2026-10-15.3'||base.ma!=='e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261')throw Error('Unexpected release/MA');
 if(await page.locator('#emotion-host .ms-direction-picker').count())throw Error('Direction picker remains');
 const caps=page.locator('#er-cap-pool [data-cap-code]'),broken=page.locator('#er-break-pool [data-break-code]');
 const capCodes=await caps.evaluateAll(els=>els.map(e=>e.dataset.capCode));
 const brokenCodes=await broken.evaluateAll(els=>els.map(e=>e.dataset.breakCode));
 if(JSON.stringify(capCodes)!==JSON.stringify(base.caps)||JSON.stringify(brokenCodes)!==JSON.stringify(base.broken))throw Error('Pool order/membership mismatch');
 if(base.pools.strength_coverage!==base.caps.length||!base.caps.length)throw Error('Cap strength incomplete');
 const heights=page.getByRole('combobox',{name:'涨停池板数',exact:true});
 const high=Object.keys(base.pools.groups).filter(k=>k!=='unknown').sort((a,b)=>Number(b)-Number(a))[0];
 await heights.selectOption(high);
 if(await caps.count()!==base.pools.groups[high].length)throw Error('Height filter count mismatch');
 await page.locator('#er-cap-pool').screenshot({path:'output/playwright/emotion-pools-caps.png'});
 await caps.locator('[data-tip]').first().hover();const tip=await page.getByRole('tooltip').innerText();if(!tip.includes('涨停'))throw Error('Strength tooltip missing');await page.mouse.move(12,12);
 await heights.selectOption('all');
 async function ime(label,key,value,attr,expected){
   const result=await page.evaluate(async({label,key,value,attr})=>{
     const el=document.querySelector('[aria-label="'+label+'"]');el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
     el.value=value;el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:value}));renderEmotion();
     const kept=document.activeElement===el&&document.querySelector('[aria-label="'+label+'"]')===el;
     el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:value}));el.dispatchEvent(new InputEvent('input',{bubbles:true,data:value}));
     await new Promise(r=>setTimeout(r,120));return {kept,q:MS_VIEW[key].q,codes:Array.from(document.querySelectorAll('['+attr+']')).map(e=>e.getAttribute(attr))};
   },{label,key,value,attr});
   if(!result.kept||result.q!==value||!result.codes.includes(expected))throw Error('IME failed '+label);
   await page.getByRole('textbox',{name:label,exact:true}).fill('');return result;
 }
 const capIME=await ime('涨停池股票搜索','emotionCaps','慈文','data-cap-code','002343');
 const breakIME=await ime('断板池股票搜索','emotionBreaks','时代','data-break-code','600241');
 const eventCheck=await page.evaluate(()=>{
   const rows=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]),by=Object.fromEntries(rows.map(r=>[r.code,r.emotion_relay]));
   const keys=DATA.emotion_relay.lists.broken;return {valid:keys.every(c=>by[c].valid&&by[c].break_watch.height>=3),
     paused:keys.includes('600825'),multiDay:keys.includes('600241')&&by['600241'].break_watch.date==='2026-10-13',
     freshBreak:keys.includes('603096')&&by['603096'].break_watch.date==='2026-10-15',
     limitDown:keys.some(c=>by[c].break_watch.labels.includes('跌停负反馈')),resealed:keys.filter(c=>by[c].break_watch.labels.includes('断板后再封板'))};
 });
 if(!eventCheck.valid||eventCheck.paused||!eventCheck.multiDay||!eventCheck.freshBreak||!eventCheck.limitDown)throw Error('Break event facts mismatch');
 await page.getByRole('textbox',{name:'断板池股票搜索',exact:true}).fill('时代');
 await page.locator('#er-break-pool').screenshot({path:'output/playwright/emotion-pools-broken.png'});
 await page.getByRole('textbox',{name:'断板池股票搜索',exact:true}).fill('');
 const promotion=[];
 for(const p of base.promotion){
   await page.locator('[data-promotion-height="'+p.height+'"]').click();
   const ids=await page.locator('#er-promotion-list [data-relay-code]').evaluateAll(els=>els.map(e=>e.dataset.relayCode));
   if(ids.length!==p.sealed||JSON.stringify(ids)!==JSON.stringify(p.success_codes))throw Error('Promotion numerator/list mismatch '+p.height);
   promotion.push({height:p.height,success:ids});
   if(p.height===2){await page.screenshot({path:'output/playwright/emotion-pools-promotion.png',fullPage:false});}
   await page.locator('#dr-x').click();
 }
 const livePromotion=base.promotion.find(p=>p.sealed>0);
 if(livePromotion){
   await page.locator('[data-promotion-height="'+livePromotion.height+'"]').click();
   const expiry=await page.evaluate(()=>{const old=erFresh;let hidden=false,restored=false;try{erFresh=()=>false;renderEmotion();hidden=document.querySelectorAll('#er-promotion-list [data-relay-code]').length===0;}finally{erFresh=old;renderEmotion();restored=document.querySelectorAll('#er-promotion-list [data-relay-code]').length>0;}return {hidden,restored};});
   if(!expiry.hidden||!expiry.restored)throw Error('Open promotion drawer retained expired quote rows');
   await page.locator('#dr-x').click();await page.evaluate(()=>renderEmotion());
   if(await page.locator('#drawer').evaluate(e=>e.classList.contains('open')))throw Error('Closed promotion drawer reopened during render');
 }
 const first=base.caps[0];await page.locator('#er-cap-pool [data-cap-code="'+first+'"]').click();await page.locator('.er-stock-detail').waitFor();
 await page.locator('.er-stock-detail>summary').click();
 if(!await page.locator('.er-stock-detail').innerText().then(t=>t.includes('同板位封板强度')&&t.includes('封单/成交额')))throw Error('Cap detail evidence missing');
 await page.locator('#dr-x').click();
 await page.locator('#er-break-pool [data-break-code="600241"]').click();await page.locator('.er-stock-detail').waitFor();await page.locator('.er-stock-detail>summary').click();
 if(!await page.locator('.er-stock-detail').innerText().then(t=>t.includes('高标断板后续')&&t.includes('2026-10-13')))throw Error('Break detail event missing');await page.locator('#dr-x').click();
 const api=await page.evaluate(async()=>{
   const version=DATA.ui_generation;
   async function csv(rows){const r=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes:rows.map(r=>r.code),contexts:{view:'emotion'}})});if(!r.ok)throw Error('CSV '+r.status);return r.text();}
   const caps=await csv(erCapRows()),broken=await csv(erBreakRows());
   if(!caps.includes('封板强度依据')||!broken.includes('高标断板后续')||!caps.includes(version)||!broken.includes(version))throw Error('CSV evidence/version missing');
   const detail=await fetch('/__ui/detail?version='+version+'&kind=stock&id=600241').then(r=>r.json());if(detail.version!==version)throw Error('Detail generation mismatch');
   return {version,capRows:caps.trim().split('\n').length-1,brokenRows:broken.trim().split('\n').length-1};
 });
 const colors=await page.locator('#er-break-pool .up,#er-break-pool .down').evaluateAll(els=>Object.fromEntries(['up','down'].map(k=>{const e=els.find(x=>x.classList.contains(k));return[k,e?getComputedStyle(e).color:null]})));
 if(colors.up!=='rgb(232, 39, 26)'||colors.down!=='rgb(18, 164, 92)')throw Error('Rise/fall colors mismatch '+JSON.stringify(colors));
 await page.setViewportSize({width:850,height:1000});await heights.selectOption(high);await page.locator('#er-cap-pool').screenshot({path:'output/playwright/emotion-pools-narrow.png'});await heights.selectOption('all');await page.setViewportSize({width:1440,height:1000});
 const status=await page.evaluate(()=>fetch('/__status').then(r=>r.json()));
 if(status.phase!=='ready'||status.code_emotion_relay_hash!==base.hash||status.snapshot_emotion_relay_hash!==base.hash)throw Error('Service code/snapshot mismatch');
 if(errors.length)throw Error(errors.join(' | '));return {generation:base.generation,hash:base.hash,source:base.source,caps:capCodes.length,broken:brokenCodes.length,strength:base.pools.strength_coverage,promotion,eventCheck,capIME,breakIME,api,colors,tip,errors,pid:status.pid};
}
