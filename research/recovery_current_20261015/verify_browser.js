async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8848/');
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 await page.locator('#ma-radar-host [data-ma-section="10"]').waitFor();
 const base=await page.evaluate(()=>{
   const rows=DATA.stocks.concat(DATA.coverage_catalog||[]),current=rows.filter(r=>r.ma_trend.recovery_current);
   return {version:DATA.ma_trend.version,hash:DATA.ma_trend.implementation_hash,generation:DATA.ui_generation,source:DATA.ma_trend.source_at,window:DATA.ma_trend.parameters.limit_recovery_candidate_days,stalePageGuard:mtStatus.toString().includes('!mtSnapshotFresh(m)'),
     current:current.map(r=>({code:r.code,name:r.name,event:r.ma_trend.recovery_candidate,status:r.ma_trend.status,pending:r.ma_trend.pending,quote_at:r.ma_trend.quote_at})),
     noncurrentEvents:rows.filter(r=>!r.ma_trend.recovery_current&&r.ma_trend.recovery_candidate).length,
     expiredExample:rows.filter(r=>r.code==='002687').map(r=>({code:r.code,status:r.ma_trend.status,current:r.ma_trend.recovery_current,event:r.ma_trend.recovery_candidate})),
     allCount:rows.length};
 });
 if(base.version!=='ma-trend-2026-10-15.4'||base.window!==5||!base.source.startsWith('2026-10-15'))throw Error('Wrong live revision/window');
 if(!base.stalePageGuard)throw Error('Latest candidate page guard not published');
 if(base.noncurrentEvents)throw Error('Historical event still exposed in summary');
 if(base.current.some(r=>r.pending||!r.event.active||r.event.age_sessions>5))throw Error('Invalid candidate in current list');
 if(base.expiredExample.some(r=>r.current))throw Error('Sixth-session candidate remains current');
 if(await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).inputValue()!=='all')throw Error('Scope default changed');
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('涨停收复');
 const filtered=await page.evaluate(()=>mtRows().map(r=>r.code));
 if(JSON.stringify(filtered.slice().sort())!==JSON.stringify(base.current.map(r=>r.code).sort()))throw Error('Candidate filter disagrees with backend');
 const selected=base.current.find(r=>r.code==='000995')||base.current[0];if(!selected)throw Error('No live candidate to inspect');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill(selected.code);
 const row=page.locator('#ma-radar-host [data-strength-id="'+selected.code+'"]');
 const text=await row.innerText();
 if((await row.locator('.ms-recovery-tag').count())!==1)throw Error('Repeated recovery badge');
 if(!text.includes('本轮收复 '+selected.event.date)||text.includes('历史启动')||text.includes('历史波段'))throw Error('Historical cycle mixed into candidate row');
 const style=await row.locator('.ms-recovery-tag').evaluate(e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();return {radius:c.borderRadius,display:c.display,gap:c.gap,background:c.backgroundColor,color:c.color,height:r.height,width:r.width,text:e.innerText};});
 if(!['inline-flex','flex'].includes(style.display)||style.radius!=='999px'||style.height<22||style.height>36)throw Error('Candidate badge layout incorrect: '+JSON.stringify(style));
 await row.locator('.ms-recovery-tag').hover();
 const tooltip=await page.getByRole('tooltip').innerText();
 if(!tooltip.includes('最近5个交易日')||!tooltip.includes('本轮事件 '+selected.event.date)||tooltip.includes('历史启动'))throw Error('Current-cycle explanation ambiguous');
 await page.mouse.move(15,15);await page.screenshot({path:'output/playwright/recovery-current-five-sessions.png',fullPage:false});
 const versions=await page.evaluate(async code=>{
   const generation=DATA.ui_generation,r=DATA.stocks.concat(DATA.coverage_catalog||[]).find(r=>r.code===code);
   const detail=await fetch('/__ui/detail?version='+generation+'&kind=stock&id='+code).then(r=>r.json());
   if(JSON.stringify(detail.item.ma_trend.recovery_candidate)!==JSON.stringify(r.ma_trend.recovery_candidate))throw Error('Candidate detail differs');
   const csv=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:generation,codes:[code,'002687'],contexts:{view:'radar',rankBoardId:'all'}})}).then(async r=>{if(!r.ok)throw Error('Export '+r.status);return r.text();});
   if(!csv.includes(generation)||!csv.includes('涨停收复候选日期'))throw Error('Export generation mismatch');
   return {generation,detailVersion:detail.version,csv};
 },selected.code);
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('002687');
 if(await page.locator('#ma-radar-host [data-strength-id="002687"] .ms-recovery-tag').count())throw Error('Expired badge visible');
 await page.getByRole('button',{name:'个股',exact:true}).click();
 await page.getByRole('combobox',{name:'个股标签',exact:true}).selectOption('涨停收复');
 await page.locator('#ms-stock-host [aria-label="强势搜索"]').fill(selected.code);
 const ranking=page.locator('#ms-stock-host [data-strength-id="'+selected.code+'"]');
 if(await ranking.locator('.ms-recovery-tag').count()!==1)throw Error('Ranking badge missing/repeated');
 await ranking.click();await page.locator('.ma-trend-detail > summary').click();
 const detailText=await page.locator('.ma-trend-detail').innerText();
 if(!detailText.includes('本轮收复 '+selected.event.date)||detailText.includes('历史波段起点'))throw Error('Detail uses historical wave');
 if(errors.length)throw Error(errors.join(' | '));
 return {base,selected,filtered,text,style,tooltip,versions,detailText,errors};
}
