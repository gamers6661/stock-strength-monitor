async (page) => {
  const base='D:/股票强势监测/research/board_opportunity_round1_20261012/screenshots/';
  const cases=[];
  for(const [id,file] of [['industry:风电设备','real-restart'],['industry:电池','real-daily-divergence']]){
    await page.evaluate(id=>showBoardById(id),id);
    await page.waitForSelector('#board-opportunity-detail');
    await page.screenshot({path:base+file+'.png'});
    await page.locator('#board-opportunity-detail').screenshot({path:base+file+'-evidence.png'});
    cases.push({id,text:await page.locator('#board-opportunity-detail').innerText()});
    await page.evaluate(()=>closeDrawer());
  }
  return {generation:await page.evaluate(()=>DATA.ui_generation),cases};
}
