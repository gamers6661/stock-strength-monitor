async (page) => {
  await page.goto('http://127.0.0.1:8848/');
  await page.getByRole('button',{name:'个股',exact:true}).click();
  await page.waitForSelector('[data-ma-section="5"]');
  const base=await page.evaluate(()=>({generation:DATA.ui_generation,version:DATA.ma_trend.version,
    hash:DATA.ma_trend.implementation_hash,counts:DATA.ma_trend.counts,ids:msRows('stocks').map(r=>r.code),
    backend:DATA.ma_trend.current,sections:Array.from(document.querySelectorAll('[data-ma-section]')).map(e=>e.dataset.maSection)}));
  if(JSON.stringify(base.ids)!==JSON.stringify(base.backend)||base.sections.join(',')!=='5,10,20')throw Error('Stage list differs from backend');
  await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('20');
  const filtered=await page.evaluate(()=>({allValid:msRows('stocks').every(r=>r.ma_trend.stage===20),
    ids:msRows('stocks').map(r=>r.code),backend:DATA.ma_trend.lists['20']}));
  if(!filtered.allValid||JSON.stringify(filtered.ids)!==JSON.stringify(filtered.backend))throw Error('Stage filter incorrect');
  await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
  const details=await page.evaluate(async()=>{
    const rows=msRows('stocks');if(!rows.length)throw Error('No live observation for detail acceptance');
    const code=rows[0].code;await showStock(code);
    const row=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).find(r=>r.code===code);
    return {code,stage:row.ma_trend.stage,support:row.ma_trend.support_price,
      text:document.querySelector('.ma-trend-detail').textContent,
      chart:!!document.getElementById('k-cv'),fullMinuteEvidence:!!row.ma_trend.tracking,
      generation:DATA.ui_generation};
  });
  if(!details.text.includes('均线趋势观察')||!details.chart||!details.fullMinuteEvidence)throw Error('Canonical detail missing');
  await page.waitForFunction(()=>document.getElementById('drawer').getBoundingClientRect().right<=innerWidth+2);
  await page.screenshot({path:'output/playwright/ma-trend-detail.png',fullPage:false});
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
  if(!composition)throw Error('IME regression');
  await page.getByRole('button',{name:'清除方向',exact:true}).click();
  await page.screenshot({path:'output/playwright/ma-trend-stages.png',fullPage:false});
  const exportResult=await page.evaluate(async()=>{
    const codes=msRows('stocks').slice(0,3).map(r=>r.code),version=DATA.ui_generation;
    const response=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes,contexts:{}})});
    const text=await response.text();return {ok:response.ok,codes,generation:version,text};
  });
  if(!exportResult.ok||!exportResult.text.includes('均线阶段')||!exportResult.text.includes('本阶段支撑触线价')||!exportResult.text.includes(base.version))throw Error('Same-version CSV failed');
  await page.getByRole('tab',{name:'情绪榜',exact:true}).click();
  const emotion=await page.evaluate(()=>({rows:msRows('stocks').length,unchanged:msRows('stocks').every(r=>r.market_strength.emotion_strong)}));
  if(!emotion.unchanged)throw Error('Emotion qualification changed');
  await page.getByRole('button',{name:'总览',exact:true}).click();
  if(!await page.getByRole('heading',{name:'均线趋势三阶段',exact:true}).count())throw Error('Overview did not use new model');
  await page.screenshot({path:'output/playwright/ma-trend-overview.png',fullPage:false});
  return {base,filtered,details,composition,exportResult,emotion};
}
