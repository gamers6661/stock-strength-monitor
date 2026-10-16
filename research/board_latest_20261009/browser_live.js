async page => {
  const errors=[];
  page.on('pageerror', e=>errors.push(String(e)));
  const results={};
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  results.model=await page.evaluate(()=>({version:DATA.board_trend_model.version,asof:DATA.board_trend_model.asof,ready:DATA.board_trend_model.ready,calendarDays:DATA.board_trend_model.calendar.length}));
  results.defaultFilter=await center.locator('[data-board-filter="watch"]').getAttribute('aria-pressed');
  if(results.defaultFilter!=='true')throw Error('默认未进入重点观察');
  await center.getByRole('button',{name:'题材',exact:true}).click();
  const searchTarget=center.getByRole('textbox',{name:'搜索板块'});
  await searchTarget.fill('电池');
  if(await center.locator('[data-board-filter="all"]').getAttribute('aria-pressed')!=='true')throw Error('搜索未查询全部目录');
  if(await center.locator('[data-board-id="industry:电池"]').count()!==1)throw Error('电池不可查询');
  results.target=await center.locator('[data-board-id="industry:电池"]').innerText();
  const expectedBattery=await page.evaluate(()=>DATA.board_catalog.find(b=>b.id==='industry:电池').index_current);
  if(!expectedBattery.ready||!results.target.includes(expectedBattery.state)||!results.target.includes(expectedBattery.confirmation))throw Error('电池实际页面与最新计算不一致');
  results.battery=expectedBattery;
  await center.locator('[data-board-id="industry:电池"] .bc-name').click();
  if(!await page.getByRole('heading',{name:'当前指数趋势',exact:true}).isVisible())throw Error('目标行业指数详情缺失');
  await page.screenshot({path:'output/playwright/board-live-latest-target.png'});
  await page.getByRole('button',{name:'×',exact:true}).click();
  await page.waitForTimeout(350);
  await searchTarget.fill('');
  results.filters=[];
  for(const kind of ['industry','theme']){
    await center.getByRole('button',{name:kind==='industry'?'行业':'题材',exact:true}).click();
    for(const key of ['watch','advance','startup','pullback','support','weak','diffusion','all']){
      await center.locator('[data-board-filter="'+key+'"]').click();
      const expected=await page.evaluate(({kind,key})=>DATA.board_catalog.filter(b=>{
        if(b.type!==kind)return false;
        if(key==='all')return true;
        if(!b.ranking_eligible)return false;
        if(key==='diffusion')return b.member_diffusion;
        const t=b.index_current;
        return t&&t.ready&&t[{watch:'priority_observation',advance:'strong_advance',startup:'startup',pullback:'pullback',support:'support_observation',weak:'weak'}[key]];
      }).map(b=>b.id).sort(),{kind,key});
      const actual=(await center.locator('.bc-card').evaluateAll(es=>es.map(e=>e.dataset.boardId))).sort();
      if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('筛选不一致 '+kind+' '+key);
      results.filters.push({kind,key,count:actual.length});
    }
  }
  await center.locator('[data-board-filter="watch"]').click();
  await page.screenshot({path:'output/playwright/board-live-latest-theme.png'});
  const tag=center.locator('.bc-card .ui-tag').first();
  await tag.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await tag.click();
  await page.waitForTimeout(200);
  if(!await page.locator('#ui-note-tip').isVisible())throw Error('标签注释未显示');
  await page.keyboard.press('Escape');
  await center.locator('.bc-name').first().click();
  if(!await page.getByRole('heading',{name:'当前指数趋势',exact:true}).isVisible())throw Error('指数详情未显示');
  await page.getByText('数据与判断依据',{exact:true}).click();
  if(!await page.getByText(/历史状态只作背景/).isVisible())throw Error('日期依据未显示');
  const detail=await page.locator('#drawer').innerText();
  if(!detail.includes('MA5>MA10')||!detail.includes('无需MA10>MA20'))throw Error('详情未展示新规则');
  await page.screenshot({path:'output/playwright/board-live-latest-detail.png'});
  const member=page.locator('#drawer tr.clickable').first();
  if(await member.count()){
    await member.click();
    results.memberNavigation=(await page.locator('#drawer').innerText()).slice(0,120);
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
  await page.screenshot({path:'output/playwright/board-live-latest-mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  await center.getByRole('button',{name:'行业',exact:true}).click();
  await center.locator('[data-board-filter="watch"]').click();
  await page.screenshot({path:'output/playwright/board-live-latest-industry.png'});
  results.pageErrors=errors;
  if(errors.length)throw Error(errors.join('\n'));
  return results;
}
