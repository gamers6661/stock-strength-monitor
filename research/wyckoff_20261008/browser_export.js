async page => {
  const before = await page.evaluate(() => ({
    snapshot: DATA.generated_at,
    structures: DATA.wyckoff_structure.count,
    expectedCodes: DATA.stocks.concat(DATA.coverage_catalog || []).map(r => r.code),
    structuredCodes: DATA.wyckoff_structure.rows.map(r => r.code)
  }));
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', {name: '导出 CSV', exact: true}).click();
  const file = await downloaded;
  await file.saveAs('D:/股票强势监测/output/playwright/wyckoff-round1-all.csv');
  console.log(JSON.stringify({snapshot: before.snapshot, structures: before.structures,
    expectedRows: before.expectedCodes.length, download: file.suggestedFilename()}));
  // 将精确名单随下载一起留存，供离线检查导出的顺序和逐股字段。
  await page.evaluate(data => { window.__round1_export_evidence = data; }, before);
}
