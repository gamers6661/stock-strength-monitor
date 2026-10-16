async page => {
  await page.getByRole('button', {name:'板块',exact:true}).click();
  await page.screenshot({path:'output/playwright/board-trend-industry.png'});
  return await page.evaluate(() => ({boardModel:DATA.board_trend_model,
    cards:document.querySelectorAll('#board-center .bc-card').length,
    filters:[...document.querySelectorAll('#board-center [data-board-filter]')].map(e=>e.textContent)}));
}
