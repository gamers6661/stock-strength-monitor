async page => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  await center.getByRole('textbox',{name:'搜索板块'}).fill('房地产');
  const card=center.locator('[data-board-id="industry:房地产"]');
  const result=await page.evaluate(()=>({generated_at:DATA.generated_at,session:DATA.session,
    phase:sessionNow(),catalogVersion:DATA.board_catalog_version,
    current_ready:DATA.board_trend_model.current_ready,current_pending:DATA.board_trend_model.current_pending,
    all:DATA.board_catalog.length,auctionHidden:boardAuction(boardById('industry:房地产'))===null}));
  if(result.catalogVersion!=='板块成员竞价4'||result.session!=='早盘'||!result.auctionHidden)throw Error('新版实际页面或开盘衔接不一致');
  result.industry=await card.innerText();
  if(result.industry.includes('主板成员竞价等权'))throw Error('盘中卡片仍显示竞价');
  await card.locator('.bc-name').click();
  await page.getByRole('heading',{name:'主板成员参与',exact:true}).waitFor();
  result.detail=await page.locator('#drawer').innerText();
  if(result.detail.includes('主板成员竞价等权'))throw Error('盘中详情仍显示竞价');
  await page.screenshot({path:'output/playwright/auction-fix-live-industry-detail.png'});
  await page.getByRole('button',{name:'×',exact:true}).click();
  await page.waitForFunction(()=>!document.getElementById('drawer').classList.contains('open'));
  await page.getByRole('button',{name:'题材',exact:true}).first().click();
  const themes=page.locator('#theme-center');
  await themes.getByRole('textbox',{name:'搜索板块'}).fill('重组蛋白');
  result.theme=await themes.locator('[data-board-id="theme:重组蛋白"]').innerText();
  if(result.theme.includes('主板成员竞价等权'))throw Error('正常题材页仍混入竞价');
  await page.screenshot({path:'output/playwright/auction-fix-live-theme.png'});
  if(errors.length)throw Error(errors.join('\n'));
  return result;
}
