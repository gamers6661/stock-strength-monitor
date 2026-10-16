async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8848/dashboard.html');
 await page.locator('#seg').getByRole('button',{name:'情绪',exact:true}).click();
 await page.locator('#er-cap-pool [data-cap-code="002343"]').click();
 await page.locator('#k-cv').waitFor();
 const real=await page.evaluate(()=>({generation:DATA.ui_generation,range:document.querySelector('[aria-label="K线显示区间"]').value,last:MS_CHART.bars.at(-1).date}));
 if(real.range!=='60'||real.last!=='2026-10-15')throw Error('Candle default/date changed');
 await page.screenshot({path:'output/playwright/kline-retry-real-candles.png',fullPage:false});
 await page.locator('#dr-x').click();
 const fixture=await page.evaluate(()=>{
  const code='002343',row=DATA.stocks.concat(DATA.coverage_catalog||[]).find(r=>r.code===code),lazy=DATA.ui_lazy;
  const test=Object.assign({},row,{chart_history:[],strength_history:[],k:[],
   chart_data_state:{kind:'suspected_suspension',label:'疑似停牌',checked_at:'2026-10-15T17:00:00',basis:'同批同源有3只股票返回有效K线，本股两次有效空响应；尚未确认停牌。'},
   emotion_relay:Object.assign({},row.emotion_relay,{valid:false,suspended_current:false,history:[]})});
  try{
   DATA.ui_lazy=false;uiPut('stock',test);showStock(code);
   return {text:document.querySelector('#dr-b').textContent,tip:Array.from(document.querySelectorAll('#dr-b [data-tip]')).find(e=>e.textContent==='疑似停牌').getAttribute('data-tip')};
  }finally{uiPut('stock',row);DATA.ui_lazy=lazy;}
 });
 if(!fixture.text.includes('疑似停牌')||!fixture.tip.includes('同批同源有3只')||!fixture.tip.includes('尚未确认停牌'))throw Error('Fixture label/evidence mismatch');
 const label=page.locator('#dr-b .ms-tag').filter({hasText:'疑似停牌'});await label.hover();
 if(!await page.getByRole('tooltip').innerText().then(t=>t.includes('两次有效空响应')))throw Error('Retry evidence tooltip missing');
 await page.screenshot({path:'output/playwright/kline-retry-suspected-fixture.png',fullPage:false});
 await page.locator('#dr-x').click();
 await page.locator('#emotion-host [data-relay-code="600825"]').first().click();
 await page.locator('#dr-b').getByText('停牌中 · 复牌后继续显示K线',{exact:true}).waitFor();
 if(await page.locator('#k-cv').count())throw Error('Known halt manufactured a candle');
 const status=await page.evaluate(()=>fetch('/__status').then(r=>r.json()));
 if(status.phase!=='ready'||status.ui_generation!==real.generation||status.last_pipeline_performance.kline_acquisition.version!=='正式日线增量3')throw Error('New acquisition not active');
 if(errors.length)throw Error(errors.join(' | '));
 return {real,known_halt_preserved:true,simulated_empty_fixture_label_verified:true,fixture_is_not_actual_stock_suspension:true,errors,pid:status.pid};
}
