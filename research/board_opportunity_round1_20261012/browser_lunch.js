async (page) => {
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.waitForFunction(()=>DATA.board_opportunity_model);
  if(await page.evaluate(()=>DATA.session)!=='午间休市')throw new Error('Not the lunch snapshot');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  await page.locator('#board-center').getByRole('button',{name:'行业',exact:true}).click();
  await page.locator('#board-center [data-board-filter="watch"]').click();
  const text=await page.locator('#board-center').innerText();
  if(!text.includes('午休保留上午结果'))throw new Error('Lunch retained label missing');
  await page.screenshot({path:'D:/股票强势监测/research/board_opportunity_round1_20261012/screenshots/lunch-current.png'});
  return {generation:await page.evaluate(()=>DATA.ui_generation),session:await page.evaluate(()=>DATA.session),counts:await page.evaluate(()=>DATA.board_opportunity_model.counts),retained_label:true};
}
