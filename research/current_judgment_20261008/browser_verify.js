async page => {
  const result={};
  await page.getByRole('button',{name:'总览',exact:true}).click();
  await page.getByRole('button',{name:/时代万恒600241/}).first().click();
  const panel=page.locator('#session-context-detail');
  await panel.scrollIntoViewIfNeeded();
  result.shidai=await panel.innerText();
  if(!result.shidai.includes('已有 160 根日线')||!result.shidai.includes('尚未形成整理')||!result.shidai.includes('20日新高突破'))throw new Error('时代万恒展示不完整');
  await panel.screenshot({path:'D:/股票强势监测/output/playwright/current-shidai.png'});
  await page.locator('#dr-x').click();
  await page.waitForTimeout(350);
  const card=page.locator('#work-consolidation-list button').filter({hasText:'新化股份603867'}).first();
  result.xinhuaCard=await card.innerText();
  if(!result.xinhuaCard.includes('反包修复')||!result.xinhuaCard.includes('原平台内承接'))throw new Error('新化股份没有最新判断');
  if(result.xinhuaCard.includes('2026-09-30 日线 A档 →'))throw new Error('旧主结论仍在显示');
  await card.screenshot({path:'D:/股票强势监测/output/playwright/current-xinhua-card.png'});
  await card.click();
  await panel.scrollIntoViewIfNeeded();
  result.xinhua=await panel.innerText();
  if(!result.xinhua.includes('已形成整理平台')||!result.xinhua.includes('原平台内承接'))throw new Error('新化结构判断错误');
  await panel.screenshot({path:'D:/股票强势监测/output/playwright/current-xinhua.png'});
  result.model=await page.evaluate(()=>({generated_at:DATA.generated_at,version:DATA.session_context.version,
    phase:sessionNow(),context:DATA.session_context,
    named:stockPoolRows().filter(r=>['600241','603867'].includes(r.code)).map(r=>({code:r.code,context:r.session_context})),
    allCount:stockPoolRows().length}));
  await page.locator('#dr-x').click();
  await page.getByRole('button',{name:'个股',exact:true}).click();
  await page.locator('#q').fill('');
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 CSV',exact:true}).click();
  const file=await download;
  result.downloadName=file.suggestedFilename();
  await file.saveAs('D:/股票强势监测/output/playwright/current-judgment-all.csv');
  return result;
}
