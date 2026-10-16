async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,close:DATA.market_strength.close_verification,coverage:DATA.market_strength.coverage,ma:DATA.ma_trend,
   rowCount:(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).length,msHash:DATA.market_strength.implementation_hash}));
 if(base.coverage.trend_valid<2800||base.ma.pending.length>300||base.ma.minute_needed!==0)throw Error('Close judgment coverage not restored');
 const header=await page.locator('#fresh-txt').innerText();if(!header.includes('正式收盘已核验')||header.includes('定点收盘报价待更新'))throw Error('Global close header still uses obsolete intraday boundary');
 const scope=page.getByRole('combobox',{name:'趋势观察范围',exact:true}),phase=page.getByRole('combobox',{name:'均线阶段',exact:true});
 await scope.selectOption('trend');await phase.selectOption('');
 const current=await page.evaluate(()=>mtRows().map(r=>r.code));if(current.length!==base.ma.current.length||!current.length)throw Error('Radar current list mismatch');
 await page.screenshot({path:'output/playwright/closing-judgment-radar.png',fullPage:false});
 for(const n of ['5','10','20']){await phase.selectOption(n);const result=await page.evaluate(()=>mtRows().map(r=>r.ma_trend.stage));if(result.length!==base.ma.counts[n]||result.some(v=>String(v)!==n))throw Error('Stage count mismatch '+n);}
 await phase.selectOption('');await scope.selectOption('pending');
 const pending=await page.evaluate(()=>mtRows().map(r=>r.ma_trend.reason));if(pending.length!==base.ma.pending.length||pending.some(x=>/非连续竞价报价|分钟记录|分钟过程/.test(x)))throw Error('Stale quote/minute pending remains');
 await scope.selectOption('all');
 const input=page.getByRole('textbox',{name:'雷达股票搜索',exact:true});await input.fill('慈文');
 const cw=page.locator('#ma-radar-host [data-strength-id="002343"]');
 if(!await cw.innerText().then(t=>t.includes('推进延续')&&!t.includes('报价待核验')))throw Error('Known close row still unverified');
 const composition=await page.evaluate(async()=>{
   const el=document.querySelector('[aria-label="雷达股票搜索"]');el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='皇台';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'皇台'}));mtRender();const kept=document.activeElement===el;
   el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'皇台'}));el.dispatchEvent(new InputEvent('input',{bubbles:true,data:'皇台'}));await new Promise(r=>setTimeout(r,120));return {kept,q:MS_VIEW.radar.q,codes:mtRows().map(r=>r.code)};
 });if(!composition.kept||!composition.codes.includes('000995'))throw Error('Radar IME regressed');
 const ht=page.locator('#ma-radar-host [data-strength-id="000995"]');await ht.locator('[data-tip]').first().hover();const tip=await page.getByRole('tooltip').innerText();await page.mouse.move(10,10);if(!tip)throw Error('Tag tooltip absent');
 await ht.click();await page.locator('.ma-trend-detail').waitFor();
 await page.locator('.ma-trend-detail>summary').click();await page.screenshot({path:'output/playwright/closing-judgment-stock.png',fullPage:false});await page.locator('#dr-x').click();
 const api=await page.evaluate(async()=>{
   const version=DATA.ui_generation;const detail=await fetch('/__ui/detail?version='+version+'&kind=stock&id=000995').then(r=>r.json());
   const r=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes:['000995','002343'],contexts:{view:'radar'}})});if(!r.ok)throw Error('Radar CSV '+r.status);const csv=await r.text();
   if(detail.version!==version||!detail.item.ma_trend.completed_daily_proof||!csv.includes(version)||!csv.includes(DATA.ma_trend.implementation_hash)||!csv.includes('正式收盘')||!csv.includes('2026-10-15 16:'))throw Error('Close detail/CSV evidence mismatch');
   return {version,rows:csv.trim().split('\n').length-1,candidate:detail.item.ma_trend.status,quote:detail.item.ma_trend.quote_at,basis:detail.item.ma_trend.judgment_basis};
 });
 await input.fill('');await page.getByRole('button',{name:'个股',exact:true}).click();
 const ranks=await page.evaluate(()=>({total:msRankRows().length,expected:msRankContext().ranking.expected,withTrend:msRankRows().filter(r=>r.market_strength.trend_score!=null).length}));
 if(ranks.total!==ranks.expected||ranks.withTrend<2800)throw Error('Full member trend rankings not restored');
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 const emotion=await page.evaluate(()=>({sealed:erModel().lists.sealed.length,broken:erModel().lists.broken.length,paused:(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).find(r=>r.code==='600825').emotion_relay}));
 if(emotion.sealed!==34||!emotion.paused.suspended_current||emotion.paused.height!==10)throw Error('Relay/halt regression');
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();await scope.selectOption('trend');
 await page.setViewportSize({width:850,height:1000});await page.screenshot({path:'output/playwright/closing-judgment-narrow.png',fullPage:false});await page.setViewportSize({width:1440,height:1000});
 if(errors.length)throw Error(errors.join(' | '));return {generation:base.generation,coverage:base.coverage,close:base.close,maCounts:base.ma.counts,pending:pending.length,current:current.length,header,composition,tip,api,ranks,emotion:{sealed:emotion.sealed,broken:emotion.broken},errors};
}
