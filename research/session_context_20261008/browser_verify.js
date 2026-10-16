async page => {
  await page.clock.setSystemTime(new Date());
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  const main = await page.evaluate(() => ({
    snapshot: DATA.generated_at, version: DATA.session_context.version,
    phase: sessionNow(), mode: WORK_MODE,
    rows: DATA.stocks.length + (DATA.coverage_catalog || []).length,
    judged: DATA.session_context.price_judged_count,
    structureJudged: DATA.session_context.structure_judged_count
  }));
  await page.locator('#work-attack-list button').first().click();
  const detail = await page.locator('#session-context-detail').innerText();
  await page.screenshot({path:'D:/股票强势监测/output/playwright/context-live-detail.png',scale:'css'});
  // 新页面清除详情覆盖，点击真实页面入口和导出按钮。
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'个股',exact:true}).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 CSV',exact:true}).click();
  const csv=await download;
  await csv.saveAs('D:/股票强势监测/output/playwright/context-round2-all.csv');
  return {main,detail,exportName:csv.suggestedFilename()};
}
