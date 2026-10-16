async page=>{
  const result={};
  await page.setViewportSize({width:1600,height:1100});
  await page.getByRole('button',{name:'总览',exact:true}).click();
  const attack=page.locator('#work-attack-list article');
  const consolidation=page.locator('#work-consolidation-list article');
  result.counts=await page.evaluate(()=>({attackDOM:document.querySelectorAll('#work-attack-list article').length,
    attackData:DATA.attack_monitor.rows.length,consolidationDOM:document.querySelectorAll('#work-consolidation-list article').length,
    consolidationData:DATA.trend_consolidation.rows.length}));
  if(result.counts.attackDOM!==result.counts.attackData||result.counts.consolidationDOM!==result.counts.consolidationData)throw Error('名单数量改变');
  result.order=await page.evaluate(()=>({attack:[...document.querySelectorAll('#work-attack-list article')].map(e=>e.dataset.stockCode),
    expectedAttack:DATA.attack_monitor.rows.map(r=>r.code),consolidation:[...document.querySelectorAll('#work-consolidation-list article')].map(e=>e.dataset.stockCode),
    expectedConsolidation:DATA.trend_consolidation.rows.map(r=>r.code)}));
  if(JSON.stringify(result.order.attack)!==JSON.stringify(result.order.expectedAttack)||JSON.stringify(result.order.consolidation)!==JSON.stringify(result.order.expectedConsolidation))throw Error('排序改变');
  await page.locator('#work-normal-monitor').screenshot({path:'D:/股票强势监测/output/playwright/layout-overview.png'});
  const shidai=attack.filter({hasText:'时代万恒'});
  await shidai.scrollIntoViewIfNeeded();
  result.attackText=await shidai.innerText();
  if(!result.attackText.includes('5.98'))throw Error('已有ATR距离未展示');
  await shidai.screenshot({path:'D:/股票强势监测/output/playwright/layout-shidai.png'});
  await shidai.getByRole('button',{name:'位置偏热，查看注释',exact:true}).click();
  result.riskNote=await page.locator('#ui-note-tip').innerText();
  if(!result.riskNote.includes('MA5'))throw Error('风险注释丢失');
  if(await page.locator('#drawer').evaluate(e=>e.classList.contains('open')))throw Error('点击标签误打开个股');
  await page.keyboard.press('Escape');
  if(await page.locator('#ui-note-tip').isVisible())throw Error('注释无法关闭');
  const xinhua=consolidation.filter({hasText:'新化股份'});
  await xinhua.scrollIntoViewIfNeeded();
  result.consolidationText=await xinhua.innerText();
  await xinhua.screenshot({path:'D:/股票强势监测/output/playwright/layout-xinhua.png'});
  await page.getByRole('button',{name:'查看国脉文化600640详情',exact:true}).click();
  const panel=page.locator('#session-context-detail');
  result.detailText=await panel.innerText();
  await panel.screenshot({path:'D:/股票强势监测/output/playwright/layout-detail-decision.png'});
  result.folded=await page.locator('#dr-b details.ui-evidence').evaluateAll(es=>es.map(e=>({summary:e.querySelector('summary').innerText,open:e.open})));
  if(result.folded.some(e=>e.open))throw Error('详细记录未默认折叠');
  const record=page.locator('#dr-b details.ui-evidence').filter({has:page.locator('summary').filter({hasText:'整理依据与确认记录'})});
  await record.locator('summary').first().click();
  if(!await record.evaluate(e=>e.open))throw Error('整理记录无法展开');
  result.recordText=await record.innerText();
  if(!result.recordText.includes('未完成的当日不计入'))throw Error('原有整理依据丢失');
  await record.locator('summary').first().click();
  await page.setViewportSize({width:390,height:844});
  await panel.scrollIntoViewIfNeeded();
  await panel.screenshot({path:'D:/股票强势监测/output/playwright/layout-detail-mobile.png'});
  result.mobile=await panel.evaluate(e=>({width:e.clientWidth,scrollWidth:e.scrollWidth,
    metricColumns:getComputedStyle(e.querySelector('.ui-metrics')).gridTemplateColumns,
    clippedTags:[...e.querySelectorAll('.ui-tag')].filter(t=>t.scrollWidth>t.clientWidth+2).length}));
  if(result.mobile.scrollWidth>result.mobile.width+2||result.mobile.clippedTags)throw Error('窄屏内容溢出');
  const basis=panel.getByRole('button',{name:'判断依据，查看注释',exact:true});
  await basis.focus();
  if(!await page.locator('#ui-note-tip').isVisible())throw Error('键盘无法读取注释');
  result.basisNote=await page.locator('#ui-note-tip').innerText();
  await page.keyboard.press('Escape');
  await page.locator('#dr-x').click();
  await page.setViewportSize({width:1600,height:1100});
  await page.getByRole('button',{name:'个股',exact:true}).click();
  result.stockRows=await page.locator('#tb-stocks tbody tr').count();
  const waitDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 CSV',exact:true}).click();
  const file=await waitDownload;
  await file.saveAs('D:/股票强势监测/output/playwright/layout-all.csv');
  result.csvName=file.suggestedFilename();
  await page.getByRole('button',{name:'选股雷达',exact:true}).click();
  result.radarRows=await page.locator('#tb-radar tr').count();
  if(!result.stockRows||!result.radarRows)throw Error('列表页无法显示');
  await page.getByRole('button',{name:'总览',exact:true}).click();
  return result;
}
