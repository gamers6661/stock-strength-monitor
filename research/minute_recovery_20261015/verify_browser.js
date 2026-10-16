async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8848/');
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 await page.locator('#ma-radar-host [data-ma-section="10"]').waitFor();
 const base=await page.evaluate(()=>({version:DATA.ma_trend.version,hash:DATA.ma_trend.implementation_hash,generation:DATA.ui_generation,source:DATA.ma_trend.source_at,fetch:DATA.ma_trend.minute_fetch,needed:DATA.ma_trend.minute_needed,requested:DATA.ma_trend.minute_requested}));
 if(base.version!=='ma-trend-2026-10-15.3'||!base.source.startsWith('2026-10-15'))throw Error('Wrong live revision/source');
 if(await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).inputValue()!=='all')throw Error('Scope default changed');
 if(await page.getByRole('combobox',{name:'均线阶段',exact:true}).inputValue()!=='')throw Error('Phase default changed');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('000995');
 const candidateRow=await page.locator('#ma-radar-host [data-strength-id="000995"]').innerText();
 if(!candidateRow.includes('涨停收复候选 2026-10-13')||!candidateRow.includes('历史启动 2026-09-21')||!candidateRow.includes('新启动候选'))throw Error('Candidate/origin dates not separated');
 await page.locator('#ma-radar-host .ms-tag').filter({hasText:/^涨停收复$/}).first().hover();
 const tooltip=await page.getByRole('tooltip').innerText();
 if(!tooltip.includes('候选事件 2026-10-13')||!tooltip.includes('不直接算作合格趋势'))throw Error('Recovery explanation missing');
 await page.screenshot({path:'output/playwright/limit-recovery-candidate.png',fullPage:false});
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('涨停收复');
 if(!await page.locator('#ma-radar-host [data-strength-id="000995"]').count())throw Error('Recovery event filter missing');
 const frozen=await page.evaluate(async()=>{
   const generation=DATA.ui_generation,r=DATA.stocks.concat(DATA.coverage_catalog||[]).find(r=>r.code==='000995');
   const detail=await fetch('/__ui/detail?version='+generation+'&kind=stock&id=000995').then(r=>r.json());
   if(JSON.stringify(detail.item.ma_trend.recovery_candidate)!==JSON.stringify(r.ma_trend.recovery_candidate))throw Error('Detail event differs');
   const csv=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:generation,codes:['000995'],contexts:{view:'radar',rankBoardId:'all'}})}).then(async r=>{if(!r.ok)throw Error('Export '+r.status);return r.text();});
   if(!csv.includes('涨停收复候选日期')||!csv.includes('2026-10-13')||!csv.includes(generation))throw Error('CSV missing same-generation candidate');
   return {generation,event:r.ma_trend.recovery_candidate,detailVersion:detail.version,csvHeader:csv.split('\n')[0]};
 });
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
 await page.locator('#ma-radar-host [aria-label="雷达股票搜索"]').fill('603235');
 const minutesRow=await page.locator('#ma-radar-host [data-strength-id="603235"]').innerText();
 const live=await page.evaluate(()=>{
   const rows=DATA.stocks.concat(DATA.coverage_catalog||[]),ms=rows.map(r=>r.ma_trend||{});
   return {source:DATA.ma_trend.source_at,pending:rows.filter(r=>(r.ma_trend||{}).status==='支撑过程待核验').map(r=>({code:r.code,name:r.name,reason:r.ma_trend.reason,coverage:r.ma_trend.minute_coverage})),
    noTrade:rows.filter(r=>(r.ma_trend.minute_coverage||{}).no_trade_minutes).map(r=>({code:r.code,name:r.name,coverage:r.ma_trend.minute_coverage,status:r.ma_trend.status})),
    candidates:rows.filter(r=>(r.ma_trend.recovery_candidate||{}).active).map(r=>({code:r.code,name:r.name,event:r.ma_trend.recovery_candidate})),
    cases:['600241','600400','002869','603701','603235'].map(c=>{const r=rows.find(r=>r.code===c);return {code:c,name:r.name,status:r.ma_trend.status,quote_at:r.ma_trend.quote_at,coverage:r.ma_trend.minute_coverage};})};
 });
 if(live.pending.length)throw Error('Unresolved live support evidence: '+JSON.stringify(live.pending));
 await page.screenshot({path:'output/playwright/minute-zero-turnover-verified.png',fullPage:false});
 await page.getByRole('button',{name:'个股',exact:true}).click();
 await page.locator('#ms-stock-host [aria-label="强势搜索"]').fill('000995');
 const ranking=await page.locator('#ms-stock-host [data-strength-id="000995"]').innerText();
 if(!ranking.includes('涨停收复'))throw Error('Stock-ranking label missing');
 if(ranking.includes('快照已过期'))throw Error('Fresh rank falsely expired');
 await page.getByRole('combobox',{name:'个股标签',exact:true}).selectOption('涨停收复');
 if(!await page.locator('#ms-stock-host [data-strength-id="000995"]').count())throw Error('Stock event filter missing');
 await page.locator('#ms-stock-host [data-strength-id="000995"]').click();
 await page.locator('.ma-trend-detail > summary').click();
 const details=await page.locator('.ma-trend-detail').innerText();
 if(!details.includes('候选日期 2026-10-13')||!details.includes('历史波段起点 2026-09-21'))throw Error('Detail dates ambiguous');
 if(errors.length)throw Error(errors.join(' | '));
 return {base,candidateRow,tooltip,frozen,live,minutesRow,ranking,details,errors};
}
