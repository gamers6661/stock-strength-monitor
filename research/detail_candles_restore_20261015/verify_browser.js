async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8848/dashboard.html');
 await page.locator('#seg').getByRole('button',{name:'情绪',exact:true}).click();
 const base=await page.evaluate(()=>({generation:DATA.ui_generation,source:DATA.quote_capture_at}));
 await page.evaluate(()=>{
  window.__candleCalls=[];const original=msDrawCandles;
  msDrawCandles=function(canvas,bars,price,count){window.__candleCalls.push({length:bars.length,count,first:bars[0].date,last:bars[bars.length-1].date});return original(canvas,bars,price,count);};
 });
 let trading=page.locator('#er-cap-pool [data-cap-code="002343"]');
 if(!await trading.count())trading=page.locator('#emotion-host [data-relay-code="002343"]');
 await trading.first().click();
 await page.locator('#k-cv').waitFor({state:'visible'});
 await page.waitForFunction(()=>window.__candleCalls.length>0);
 const chart=await page.evaluate(()=>({calls:window.__candleCalls.slice(),range:document.querySelector('[aria-label="K线显示区间"]').value,
   source:(DATA.stocks.concat(DATA.coverage_catalog||[]).find(x=>x.code==='002343')||{}).chart_source,
   readout:document.querySelector('#k-readout').textContent}));
 if(chart.range!=='60'||chart.calls[0].count!==60||chart.calls[0].last!=='2026-10-15')throw Error('Default candle range/date mismatch '+JSON.stringify(chart));
 const canvas=page.locator('#k-cv');await canvas.hover({position:{x:150,y:80}});
 if(!await page.locator('#k-readout').innerText().then(t=>t.includes('开 ')&&t.includes('高 ')&&t.includes('低 ')&&t.includes('收 ')))throw Error('Candle OHLC readout missing');
 await page.screenshot({path:'output/playwright/detail-candles-restored.png',fullPage:false});
 await page.getByRole('combobox',{name:'K线显示区间',exact:true}).selectOption('20');
 const last=await page.evaluate(()=>window.__candleCalls.at(-1));if(last.count!==20)throw Error('Candle range control failed');
 await page.locator('#dr-x').click();
 let halted=page.locator('#emotion-host [data-relay-code="600825"]');
 if(!await halted.count())halted=page.locator('.er-core').filter({hasText:'600825'});
 await halted.first().click();
 await page.locator('#dr-b').getByText('停牌中 · 复牌后继续显示K线',{exact:true}).waitFor();
 if(await page.locator('#k-cv').count())throw Error('Halted stock should not manufacture a chart');
 await page.screenshot({path:'output/playwright/detail-halted-label.png',fullPage:false});
 const status=await page.evaluate(()=>fetch('/__status').then(r=>r.json()));
 if(status.phase!=='ready'||status.ui_generation!==base.generation)throw Error('Service/UI generation changed during acceptance');
 if(errors.length)throw Error(errors.join(' | '));
 return {base,chart,range20:true,haltedLabel:true,errors};
}
