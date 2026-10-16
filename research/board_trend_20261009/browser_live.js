async page => {
  const errors=[];
  page.on('pageerror', e=>errors.push(String(e)));
  const results={};
  // 独立快照验收时关闭后台版本轮询，避免行情更新把静态预览反复重载。
  // -- live验收时由命令切换到根页面；静态预览明确保留独立路径。
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  results.model=await page.evaluate(()=>DATA.board_trend_model);
  results.filters=[];
  for(const kind of ['industry','theme']){
    await center.getByRole('button',{name:kind==='industry'?'行业':'题材',exact:true}).click();
    for(const key of ['all','online','initial','pullback','weakening','diffusion']){
      await center.locator('[data-board-filter="'+key+'"]').click();
      const expected=await page.evaluate(({kind,key})=>DATA.board_catalog.filter(b=>{
        if(b.type!==kind||!b.valid_members)return false;
        if(key==='all')return true;
        if(!b.ranking_eligible)return false;
        if(key==='diffusion')return b.member_diffusion;
        const t=b.index_trend;
        return t&&t.ready&&t[{online:'trend_online',initial:'initial_strength',pullback:'pullback',weakening:'weakening'}[key]];
      }).map(b=>b.id).sort(),{kind,key});
      const actual=(await center.locator('.bc-card').evaluateAll(es=>es.map(e=>e.dataset.boardId))).sort();
      if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('筛选不一致 '+kind+' '+key);
      results.filters.push({kind,key,count:actual.length});
    }
  }
  await center.locator('[data-board-filter="online"]').click();
  await page.screenshot({path:'output/playwright/board-trend-theme-live.png'});
  await center.locator('.bc-card .ui-tag').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await center.locator('.bc-card .ui-tag').first().click();
  await page.waitForTimeout(200);
  if(!await page.locator('#ui-note-tip').isVisible())throw Error('标签注释未显示');
  await page.keyboard.press('Escape');
  await center.locator('.bc-name').first().click();
  if(!await page.getByRole('heading',{name:'指数趋势',exact:true}).isVisible())throw Error('指数详情未显示');
  await page.getByText('数据与判断依据',{exact:true}).click();
  if(!await page.getByText(/22个连续交易日已对齐/).isVisible())throw Error('日期依据未显示');
  await page.screenshot({path:'output/playwright/board-trend-detail-live.png'});
  const member=page.locator('#drawer tr.clickable').first();
  if(await member.count()){
    await member.click();
    results.memberNavigation=await page.locator('#drawer').innerText();
    results.memberNavigation=results.memberNavigation.slice(0,120);
  }
  await page.getByRole('button',{name:'×',exact:true}).click();
  await page.waitForTimeout(350);
  const search=center.getByRole('textbox',{name:'搜索板块'});
  await search.fill('不存在的板块XYZ');
  if(await center.locator('.bc-card').count())throw Error('空搜索有错误结果');
  await search.fill('');
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(350);
  results.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  if(results.mobileOverflow)throw Error('手机页面横向溢出');
  await page.screenshot({path:'output/playwright/board-trend-mobile-live.png'});
  await page.setViewportSize({width:1440,height:1000});
  await center.getByRole('button',{name:'行业',exact:true}).click();
  await center.locator('[data-board-filter="all"]').click();
  await page.screenshot({path:'output/playwright/board-trend-industry-live.png'});
  results.pageErrors=errors;
  if(errors.length)throw Error(errors.join('\n'));
  return results;
}
