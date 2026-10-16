async (page) => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.goto('http://127.0.0.1:8848/');
  await page.getByRole('button',{name:'选股雷达',exact:true}).click();
  await page.locator('#ma-radar-host [data-ma-section="5"]').waitFor();
  const base=await page.evaluate(()=>({generation:DATA.ui_generation,version:DATA.ma_trend.version,hash:DATA.ma_trend.implementation_hash,
    source:DATA.ma_trend.source_at,captured:DATA.quote_capture_at,daily:DATA.strength_model.asof,counts:DATA.ma_trend.counts,
    ids:mtRows().map(r=>r.code),backend:DATA.ma_trend.current,sections:Array.from(document.querySelectorAll('#ma-radar-host [data-ma-section]')).map(e=>e.dataset.maSection),
    fresh:mtRows().every(r=>mtSnapshotFresh(r.ma_trend)),validQuoteCount:DATA.stocks.concat(DATA.coverage_catalog||[]).filter(r=>r.ma_trend.quote_at).length,
    closeReference:DATA.market_strength_close_reference}));
  if(base.version!=='ma-trend-2026-10-14.3'||JSON.stringify(base.ids)!==JSON.stringify(base.backend)||!base.fresh||!base.source||base.validQuoteCount<100||base.sections.join(',')!=='5,10,20')throw Error('Radar membership or freshness mismatch');
  const phases=[];
  for(const phase of ['5','10','20']){
    await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption(phase);
    const result=await page.evaluate(()=>({ids:mtRows().map(r=>r.code),backend:DATA.ma_trend.lists[MS_VIEW.radar.phase]}));
    if(JSON.stringify(result.ids)!==JSON.stringify(result.backend))throw Error('Radar phase mismatch '+phase);phases.push({phase,count:result.ids.length});
  }
  await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
  const stageTag=page.locator('#ma-radar-host [data-tip]').first();await stageTag.hover();
  await page.getByRole('tooltip').waitFor({state:'visible'});const radarTip=await page.getByRole('tooltip').innerText();
  if(!radarTip.includes('MA5'))throw Error('Stage tooltip absent');
  await page.screenshot({path:'output/playwright/ma-radar-new.png',fullPage:false});
  await page.getByRole('button',{name:'个股',exact:true}).click();
  if(await page.locator('#p-stocks [data-ma-section]').count())throw Error('MA radar still overrides stocks');
  const input=page.locator('#ms-stock-host [aria-label="搜索板块题材"]');
  const composition=await input.evaluate(el=>{el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='dian';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));msRender('stocks');const alive=el.isConnected&&document.activeElement===el;el.value='电池';el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'电池'}));el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false}));return alive;});
  await page.waitForFunction(()=>MS_VIEW.stocks.boardQuery==='电池'&&document.querySelector('#ms-stock-host [aria-label="搜索板块题材"]').value==='电池'&&!document.querySelector('#ms-stock-host [aria-label="搜索板块题材"]')._msEnding);
  if(!composition)throw Error('IME composing input replaced');
  const chosen=await page.evaluate(()=>{const b=msBoardCatalog().filter(b=>b.name.includes('电池')&&b.member_codes.length>0).sort((a,b)=>b.member_codes.length-a.member_codes.length)[0];return {id:b.id,name:b.name};});
  await page.locator('#ms-stock-host .ms-direction-browser').getByRole('button',{name:chosen.name,exact:true}).click();
  const board=await page.evaluate(()=>{var ctx=msRankContext();return {id:ctx.id,name:ctx.name,expected:ctx.ranking.all,actual:msRows('stocks').map(r=>r.code),items:ctx.ranking.items,view:{scope:MS_VIEW.stocks.scope,sort:MS_VIEW.stocks.sort},generation:DATA.ui_generation};});
  if(JSON.stringify(board.actual)!==JSON.stringify(board.expected)||board.view.scope!=='all')throw Error('Incomplete board membership ranking');
  await page.waitForFunction(()=>{const rows=Array.from(document.querySelectorAll('#ms-stock-host [data-strength-id]')).map(e=>e.dataset.strengthId);return JSON.stringify(rows)===JSON.stringify(msRows('stocks').slice(0,MS_VIEW.stocks.limit).map(r=>r.code));});
  const independentEmotion=await page.evaluate(()=>{const r=msRows('stocks').slice(0,MS_VIEW.stocks.limit).find(r=>r.ma_trend.pending&&r.market_strength.emotion_strong);if(!r)return {caseAvailable:false};const node=document.querySelector('#ms-stock-host [data-strength-id="'+r.code+'"]');return {caseAvailable:true,code:r.code,shown:Array.from(node.querySelectorAll('.ms-tag')).some(e=>e.textContent==='情绪强势')};});
  if(independentEmotion.caseAvailable&&!independentEmotion.shown)throw Error('MA pending hides independent emotion');
  const memberTag=page.locator('#ms-stock-host .ms-tag[data-tip]').first();await memberTag.hover();await page.getByRole('tooltip').waitFor({state:'visible'});const stockTip=await page.getByRole('tooltip').innerText();
  if(stockTip.length<15)throw Error('Stock tooltip too short');await memberTag.focus();if(!await page.getByRole('tooltip').isVisible())throw Error('Focus tooltip absent');
  await page.screenshot({path:'output/playwright/board-complete-ranks.png',fullPage:false});
  while(await page.locator('#ms-stock-host [data-strength-id]').count()<board.expected.length){await page.locator('#ms-stock-host').getByRole('button',{name:/加载更多/}).click();}
  const renderedMembers=await page.locator('#ms-stock-host [data-strength-id]').evaluateAll(nodes=>nodes.map(e=>e.dataset.strengthId));
  if(JSON.stringify(renderedMembers)!==JSON.stringify(board.expected))throw Error('Full member list cannot be rendered');
  const code=board.actual.find(c=>!board.items[c].missing);await page.locator('#ms-stock-host [aria-label="强势搜索"]').fill(code);
  const filtered=await page.evaluate(()=>({ids:msRows('stocks').map(r=>r.code),rank:document.querySelector('#ms-stock-host [data-strength-id]').getAttribute('data-board-rank')}));
  if(filtered.ids.join(',')!==code||Number(filtered.rank)!==board.items[code].rank)throw Error('Search renumbers board rank');
  await page.locator('#ms-stock-host [aria-label="强势搜索"]').fill('');
  const downloadPromise=page.waitForEvent('download');await page.locator('#ms-stock-host').getByRole('button',{name:'导出当前完整排名 CSV',exact:true}).click();
  const download=await downloadPromise;await download.saveAs('research/ma_radar_transition_20261014/browser_board_ranks.csv');
  const details=await page.evaluate(async(code)=>{await showStock(code);const card=document.querySelector('.ma-trend-detail'),canvas=document.getElementById('k-cv');return {code,folded:!!card&&!card.open,afterChart:!!canvas&&!!(canvas.compareDocumentPosition(card)&4),lastCard:card===document.getElementById('dr-b').lastElementChild};},code);
  if(!details.folded||!details.afterChart||!details.lastCard)throw Error('Detail evidence is not folded after chart');
  await page.getByRole('button',{name:'×',exact:true}).click();
  const examples=await page.evaluate(()=>DATA.stocks.concat(DATA.coverage_catalog||[]).filter(r=>['贝瑞基因','澳洋健康'].includes(r.name)).map(r=>({code:r.code,name:r.name,stage:r.ma_trend.stage,status:r.ma_trend.status,reason:r.ma_trend.reason,origin:r.ma_trend.origin&&r.ma_trend.origin.date,last_confirmation:r.ma_trend.last_confirmation&&r.ma_trend.last_confirmation.date,history_days:r.ma_trend.history_days,asof:r.ma_trend.asof,source:r.ma_trend.quote_at,last_exit:r.ma_trend.last_exit})));
  if(examples.some(r=>r.asof!=='2026-10-14'))throw Error('Example history not latest completed day');
  await page.getByRole('button',{name:'选股雷达',exact:true}).click();
  await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('advance');
  const advance=await page.evaluate(()=>({actual:mtRows().map(r=>r.code),expected:DATA.ma_trend.advance}));if(JSON.stringify(advance.actual)!==JSON.stringify(advance.expected))throw Error('Advance membership mismatch');
  await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('trend');
  const radarInput=page.locator('#ma-radar-host [aria-label="搜索板块题材"]');
  const radarComposition=await radarInput.evaluate(el=>{el.focus();el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='yi';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));mtRender();const alive=el.isConnected&&document.activeElement===el;el.value='医药';el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'医药'}));return alive;});
  await page.waitForFunction(()=>MS_VIEW.radar.boardQuery==='医药');if(!radarComposition)throw Error('Radar IME input replaced');
  await page.locator('#ma-radar-host').getByRole('button',{name:'清除方向',exact:true}).click();
  const radarCsv=await page.evaluate(async()=>{const codes=mtRows().slice(0,3).map(r=>r.code),version=DATA.ui_generation;const r=await fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,codes,contexts:{view:'radar'}})});const text=await r.text();return {ok:r.ok,count:codes.length,head:text.split('\n')[0],generation:version};});
  if(!radarCsv.ok||!radarCsv.head.includes('本阶段支撑触线价'))throw Error('Radar CSV format wrong');
  if(errors.length)throw Error('Browser errors '+errors.join(' | '));
  return {base,phases,radarTip,composition,radarComposition,chosen,board,renderedMembers:renderedMembers.length,independentEmotion,stockTip,filtered,details,examples,advanceCount:advance.actual.length,radarCsv,errors};
}
