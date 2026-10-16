async page=>{
  const result={};
  await page.setViewportSize({width:1600,height:1100});
  await page.getByRole('button',{name:'总览',exact:true}).click();
  if(await page.locator('#work-trend-comparison,[data-trend-line]').count())throw Error('旧均线板块未移除');
  const section=page.locator('#work-followup-section');
  await section.locator('summary').first().click();
  result.followup=await page.evaluate(()=>({count:document.querySelectorAll('#work-consolidation-pending article').length,
    codes:[...document.querySelectorAll('#work-consolidation-pending article')].map(e=>e.dataset.stockCode),
    expected:[...(DATA.trend_consolidation.completed_rows||[]),...(DATA.trend_consolidation.pending_rows||[]),...(DATA.trend_consolidation.withdrawn_rows||[])].map(r=>r.code),
    attack:document.querySelectorAll('#work-attack-list article').length,consolidation:document.querySelectorAll('#work-consolidation-list article').length}));
  if(JSON.stringify(result.followup.codes)!==JSON.stringify(result.followup.expected))throw Error('跟踪名单或排序改变');
  await section.scrollIntoViewIfNeeded();
  await section.screenshot({path:'D:/股票强势监测/output/playwright/followup-cards.png'});
  const first=page.locator('#work-consolidation-pending article').first();
  result.first=await first.innerText();
  await first.getByRole('button',{name:'跟踪依据，查看注释',exact:true}).click();
  result.followupNote=await page.locator('#ui-note-tip').innerText();
  if(await page.locator('#drawer').evaluate(e=>e.classList.contains('open')))throw Error('标签误打开详情');
  await page.keyboard.press('Escape');
  result.labels=await page.evaluate(()=>{
    const pool=stockPoolRows(),by=Object.fromEntries(pool.map(s=>[s.code,s]));
    const samples=[5,10,20].map(period=>{
      const board=DATA['trend_ma'+period+'_observation'];
      const row=board.main_rows.find(r=>by[r.code]&&by[r.code].trend_online===1);
      if(!row)throw Error('缺少MA'+period+'实际样本');
      const tags=uiTrendPullbackItems(by[row.code]);
      if(!tags.some(t=>t.period===period&&t.kind==='near'))throw Error('近线标签丢失');
      if(uiTrendPullbackItems(Object.assign({},by[row.code],{trend_online:0})).length)throw Error('无趋势错误标记回踩');
      return {period,code:row.code,name:by[row.code].name,tags};
    });
    const bad=pool.filter(s=>!(s.trend_online===1||s.trend_online===true)&&uiTrendPullbackItems(s).length);
    if(bad.length)throw Error('非趋势股票存在回踩标签');
    const mismatches=[];
    for(const s of pool){
      for(const tag of uiTrendPullbackItems(s)){
        if(tag.kind==='daily'){
          if(!s.historical_pullback_shape)throw Error('无历史依据标签');
        }else{
          const board=DATA['trend_ma'+tag.period+'_observation'];
          const source=(tag.kind==='reclaim'?board.reclaim_rows:board.main_rows).find(r=>r.code===s.code);
          if(!source)mismatches.push(s.code);
        }
      }
    }
    if(mismatches.length)throw Error('新增无来源回踩标签');
    const reclaimed=[5,10,20].flatMap(period=>DATA['trend_ma'+period+'_observation'].reclaim_rows.map(r=>({period,code:r.code}))).find(r=>by[r.code]&&by[r.code].trend_online===1);
    if(reclaimed&&!uiTrendPullbackItems(by[reclaimed.code]).some(t=>t.kind==='reclaim'&&t.period===reclaimed.period))throw Error('收复标签丢失');
    const without=pool.find(s=>s.trend_online===1&&!s.historical_pullback_shape&&!uiTrendPullbackItems(s).length);
    if(!without)throw Error('未验证趋势但未发生回踩情形');
    return {samples,reclaimed,trendWithoutPullback:without.code,
      labeledStocks:pool.filter(s=>uiTrendPullbackItems(s).length).length,nonTrendLabeled:bad.length};
  });
  await page.getByRole('button',{name:'个股',exact:true}).click();
  for(const sample of result.labels.samples){
    await page.locator('#q').fill(sample.code);
    const row=page.locator('#tb-stocks tbody tr').filter({hasText:sample.code}).first();
    await row.waitFor();
    if(!await row.locator('[data-pullback-period="'+sample.period+'"]').count())throw Error('个股表标签丢失');
    if(sample.period===5)await page.locator('#p-stocks .tw').screenshot({path:'D:/股票强势监测/output/playwright/pullback-stock-list.png'});
    await row.locator('.nm').click();
    const panel=page.locator('#stock-trend-pullbacks');
    await panel.waitFor();
    const tag=panel.locator('[data-pullback-period="'+sample.period+'"]').first();
    await tag.click();
    sample.note=await page.locator('#ui-note-tip').innerText();
    if(!sample.note.includes('≤1%'))throw Error('近线规则注释丢失');
    await page.keyboard.press('Escape');
    if(sample.period===5){
      await page.locator('#session-context-detail').scrollIntoViewIfNeeded();
      await page.locator('#session-context-detail').screenshot({path:'D:/股票强势监测/output/playwright/pullback-stock-detail.png'});
    }
    await page.locator('#dr-x').click();
    await page.waitForTimeout(350);
  }
  await page.locator('#q').fill('');
  await page.waitForTimeout(220);
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 CSV',exact:true}).click();
  const file=await download;
  await file.saveAs('D:/股票强势监测/output/playwright/followup-layout-all.csv');
  result.csvName=file.suggestedFilename();
  await page.getByRole('button',{name:'总览',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await section.scrollIntoViewIfNeeded();
  await first.screenshot({path:'D:/股票强势监测/output/playwright/followup-mobile.png'});
  result.mobile=await first.evaluate(e=>({width:e.clientWidth,scrollWidth:e.scrollWidth}));
  if(result.mobile.scrollWidth>result.mobile.width+2)throw Error('跟踪卡片窄屏溢出');
  await page.setViewportSize({width:1600,height:1100});
  return result;
}
