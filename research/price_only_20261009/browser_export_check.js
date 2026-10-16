async (page) => {
  await page.getByRole('button',{name:'个股',exact:true}).click();
  const pending=page.waitForEvent('download');
  await page.locator('#btn-export').click();
  const download=await pending;
  await download.saveAs('research/price_only_20261009/price_only_export.csv');
  const notes=await page.locator('#ui-attack-rules').evaluate(el=>Array.from(el.querySelectorAll('[data-ui-note]')).map(x=>x.dataset.uiNote));
  if(notes.some(x=>/资金|85%|15%/.test(x)))throw new Error('进攻规则仍有资金权重');
  await page.getByRole('button',{name:'总览',exact:true}).click();
  return {filename:download.suggestedFilename(),attackRules:notes};
}
