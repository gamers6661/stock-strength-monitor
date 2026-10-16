async (page) => {
  await page.goto('http://127.0.0.1:8848/');
  await page.getByRole('button',{name:'个股',exact:true}).click();
  await page.waitForSelector('[data-ma-section="5"]');
  const base=await page.evaluate(()=>({generation:DATA.ui_generation,version:DATA.ma_trend.version,
    hash:DATA.ma_trend.implementation_hash,counts:DATA.ma_trend.counts,source:DATA.ma_trend.source_at,
    captured:DATA.quote_capture_at,ids:msRows('stocks').map(r=>r.code),backend:DATA.ma_trend.current,
    sourceAges:msRows('stocks').map(r=>(Date.now()-parseDT(r.ma_trend.quote_at).getTime())/1000),
    ma20:msRows('stocks').filter(r=>r.ma_trend.stage===20).map(r=>r.ma_trend),
    sections:Array.from(document.querySelectorAll('[data-ma-section]')).map(e=>e.dataset.maSection)}));
  if(base.version!=='ma-trend-2026-10-14.2'||JSON.stringify(base.ids)!==JSON.stringify(base.backend)||base.sections.join(',')!=='5,10,20')throw Error('Current stage membership differs');
  if(base.sourceAges.some(a=>a>600||a< -90))throw Error('Stale current quote');
  if(base.ma20.some(m=>m.support_price!==m.platform.low||m.platform.rise_pct<20||m.platform.rise_atr<4))throw Error('MA20 floor/rise contract incorrect');
  await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('20');
  const filtered=await page.evaluate(()=>({ids:msRows('stocks').map(r=>r.code),backend:DATA.ma_trend.lists['20']}));
  if(JSON.stringify(filtered.ids)!==JSON.stringify(filtered.backend))throw Error('MA20 filter incorrect');
  await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
  const details=await page.evaluate(async()=>{
    const code=msRows('stocks')[0]?.code||DATA.ma_trend.advance[0]||DATA.stocks[0].code;
    await showStock(code);const card=document.querySelector('.ma-trend-detail'),canvas=document.getElementById('k-cv');
    const row=DATA.stocks.concat(DATA.coverage_catalog||[]).find(r=>r.code===code);
    return {code,generation:DATA.ui_generation,support:row.ma_trend.support_price,
      folded:card.tagName==='DETAILS'&&!card.open,afterChart:!!(canvas.compareDocumentPosition(card)&4),
      lastCard:card===document.getElementById('dr-b').lastElementChild,summary:card.querySelector('summary').textContent,
      source:row.ma_trend.quote_at,chart:!!canvas,model:row.ma_trend};
  });
  if(!details.folded||!details.afterChart||!details.lastCard||!details.chart)throw Error('Detailed model card was not moved and folded');
  await page.waitForFunction(()=>document.getElementById('drawer').getBoundingClientRect().right<=innerWidth+2);
  await page.screenshot({path:'output/playwright/ma-refined-detail-top.png',fullPage:false});
  await page.locator('.ma-trend-detail').scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/ma-refined-detail-folded.png',fullPage:false});
  await page.locator('.ma-trend-detail > summary').click();
  if(!await page.locator('.ma-trend-detail[open]').count())throw Error('Fold cannot open');
  await page.getByRole('button',{name:'×',exact:true}).click();
  const input=page.getByRole('textbox',{name:'搜索板块题材',exact:true});
  const composition=await input.evaluate(el=>{
    el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    el.value='dian';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));msRender('stocks');
    const alive=el.isConnected&&document.activeElement===el;
    el.value='电池';el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'电池'}));
    el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false}));return alive;
  });
  await page.waitForFunction(()=>MS_VIEW.stocks.boardQuery==='电池'&&document.querySelector('[aria-label="搜索板块题材"]').value==='电池');
  if(!composition)throw Error('Composition input broken');
  await page.getByRole('button',{name:'清除方向',exact:true}).click();
  await page.screenshot({path:'output/playwright/ma-refined-stages.png',fullPage:false});
  await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('advance');
  const advance=await page.evaluate(()=>({ids:msRows('stocks').map(r=>r.code),backend:DATA.ma_trend.advance}));
  if(JSON.stringify(advance.ids)!==JSON.stringify(advance.backend))throw Error('Advance scope incorrect');
  await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('trend');
  const exportResult=await page.evaluate(async()=>{
    const codes=msRows('stocks').slice(0,3).map(r=>r.code),version=DATA.ui_generation;
    const rows=msRows('stocks').slice(0,3).map(r=>({code:r.code,support:r.ma_trend.support_price}));
    const response=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes,contexts:{}})});
    return {ok:response.ok,codes,generation:version,rows,text:await response.text()};
  });
  if(!exportResult.ok||!exportResult.text.includes('防守依据')||!exportResult.text.includes(base.version))throw Error('CSV missing new evidence');
  await page.getByRole('tab',{name:'情绪榜',exact:true}).click();
  const emotion=await page.evaluate(()=>({rows:msRows('stocks').length,unchanged:msRows('stocks').every(r=>r.market_strength.emotion_strong)}));
  if(!emotion.unchanged)throw Error('Emotion qualification changed');
  await page.getByRole('button',{name:'总览',exact:true}).click();
  if(!await page.getByRole('heading',{name:'均线趋势三阶段',exact:true}).count())throw Error('Overview missing');
  return {base,filtered,details,composition,advance,exportResult,emotion};
}
