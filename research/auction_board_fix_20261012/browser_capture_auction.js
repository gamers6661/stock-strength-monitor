async page => {
  await page.clock.setSystemTime(new Date('2026-10-12T09:25:30+08:00'));
  await page.evaluate(()=>{DATA.session='竞价结束';closeDrawer();});
  await page.clock.runFor(400);
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  const result={};
  for(const [id,name,kind] of [['industry:房地产','房地产','industry'],['theme:重组蛋白','重组蛋白','theme']]){
    await center.getByRole('textbox',{name:'搜索板块'}).fill(name);
    await page.clock.runFor(400);
    result[kind]=await center.locator('[data-board-id="'+id+'"]').innerText();
    await page.screenshot({path:'output/playwright/auction-fix-'+kind+'.png'});
  }
  return result;
}
