async page => {
  await page.locator('#dr-x').click({timeout:1000}).catch(()=>{});
  await page.getByRole('button',{name:'总览',exact:true}).click();
  await page.setViewportSize({width:1600,height:1000});
  await page.waitForTimeout(350);
  const card=page.locator('#work-consolidation-list button').filter({hasText:'新化股份603867'}).first();
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({path:'D:/股票强势监测/output/playwright/current-xinhua-card.png'});
  return {text:await card.innerText()};
}
