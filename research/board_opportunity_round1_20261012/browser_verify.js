async (page) => {
  const base='D:/股票强势监测/research/board_opportunity_round1_20261012/';
  const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setViewportSize({width:1560,height:1100});
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.waitForFunction(()=>DATA.board_opportunity_model);
  const result={url:page.url(),generation:await page.evaluate(()=>DATA.ui_generation),screens:[],filters:[],errors:errors};
  await page.getByRole('button',{name:'板块',exact:true}).click();
  for(const kind of ['industry','theme']){
    await page.locator('#board-center').getByRole('button',{name:kind==='industry'?'行业':'题材',exact:true}).click();
    for(const [key,name] of [['watch','current'],['mainline','mainline'],['new_start','startup'],['restart','restart'],['daily','daily'],['pending','pending']]){
      await page.locator('#board-center [data-board-filter="'+key+'"]').click();
      const actual=await page.locator('#board-center .bc-card').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-board-id')));
      const expected=await page.evaluate(({kind,name})=>DATA.board_opportunity_model.lists[name].filter(id=>boardById(id).type===kind),{kind,name});
      if(JSON.stringify(actual)!==JSON.stringify(expected))throw new Error(kind+' '+key+' card/list mismatch');
      if(await page.locator('#board-center').getByRole('button',{name:'机会固定排序',exact:true}).count()!==1)throw new Error('Fixed backend sorting is not labelled');
      if((await page.locator('#board-center .bc-card-foot').allTextContents()).some(x=>x.includes('成员今日')))throw new Error('Legacy card return mixed with opportunity return');
      const file='screenshots/'+kind+'-'+name+'.png';
      await page.screenshot({path:base+file});
      result.screens.push(file);result.filters.push({kind:key,board_type:kind,count:actual.length,ids:actual});
    }
  }
  await page.getByRole('button',{name:'题材',exact:true}).first().click();
  await page.locator('#theme-center [data-board-filter="restart"]').click();
  await page.screenshot({path:base+'screenshots/theme-page-restart-empty.png'});
  result.screens.push('screenshots/theme-page-restart-empty.png');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const detailId=await page.evaluate(()=>{
    const candidate=boardCatalog().find(b=>b.opportunity.startup_raw);
    return candidate?candidate.id:DATA.board_opportunity_model.lists.daily[0];
  });
  await page.evaluate(id=>showBoardById(id),detailId);
  await page.waitForSelector('#board-opportunity-detail');
  await page.screenshot({path:base+'screenshots/detail-overview.png'});
  const tables=page.locator('#board-opportunity-detail .opportunity-checks');
  for(let i=0;i<await tables.count();i++)await tables.nth(i).screenshot({path:base+'screenshots/detail-criteria-'+i+'.png'});
  result.detail={id:detailId,criteria_tables:await tables.count(),text:await page.locator('#board-opportunity-detail').innerText()};
  await page.evaluate(()=>closeDrawer());
  await page.locator('#board-center').getByRole('button',{name:'行业',exact:true}).click();
  await page.locator('#board-center [data-board-filter="daily"]').click();
  const downloaded=page.waitForEvent('download');
  await page.locator('#board-center').getByRole('button',{name:'导出当前板块依据',exact:true}).click();
  const download=await downloaded;
  await download.saveAs(base+'browser_board_export.json');
  result.export={suggested_name:download.suggestedFilename(),file:'browser_board_export.json'};
  await page.locator('#board-center .bc-search').fill('不存在的机会_验收');
  if(await page.locator('#board-center .bc-card').count()!==0)throw new Error('Empty search has cards');
  result.empty_text=await page.locator('#board-center .bc-empty').innerText();
  await page.screenshot({path:base+'screenshots/empty-search.png'});
  await page.locator('#board-center .bc-search').fill('');
  result.final_generation=await page.evaluate(()=>DATA.ui_generation);
  result.counts=await page.evaluate(()=>DATA.board_opportunity_model.counts);
  if(result.generation!==result.final_generation)throw new Error('Generation changed during browser verification; rerun');
  if(errors.length)throw new Error(JSON.stringify(errors));
  return result;
}
