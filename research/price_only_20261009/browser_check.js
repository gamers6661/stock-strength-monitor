async (page) => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.waitForFunction(()=>typeof DATA==='object'&&DATA.close_strong_board);
  const summary=await page.evaluate(()=>({fundVersion:DATA.fund_reference_version,
    fundedRows:DATA.stocks.filter(s=>s.fund_today_yi!=null||s.fund_positive_all!=null).length,
    brokenPriceFactors:DATA.stocks.filter(s=>s.factors.rs!==s.score||s.factors.sector!==s.industry_breadth).length,
    fundColumns:Object.keys(STATE_LABEL).filter(k=>k==='fundpos'),
    date:DATA.close_strong_board.asof,count:DATA.close_strong_board.count,
    selected:document.querySelector('#work-switch button.on').dataset.work}));
  if(summary.fundVersion!=='不使用资金流1'||summary.fundedRows||summary.fundColumns.length||summary.brokenPriceFactors)throw new Error(JSON.stringify(summary));
  await page.locator('#work-close-table tbody tr').first().click();
  const detail=await page.locator('#drawer').innerText();
  if(/资金待核验|历史资金|当日主力净额|当日超大单净额|资金与数据口径/.test(detail))throw new Error('个股详情仍有资金参考');
  const source=await page.getByText('归属与数据来源',{exact:true}).count();
  if(!source)throw new Error('移除资金后归属详情丢失');
  await page.screenshot({path:'output/playwright/price-only-detail-20261009.png'});
  await page.locator('#drawer').getByRole('button',{name:'×',exact:true}).click();
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const board=await page.locator('#p-boards').innerText();
  if(/资金强度|资金潜伏|资金真实覆盖|主力净额/.test(board))throw new Error('板块仍有资金入口');
  const battery=await page.getByText('电池',{exact:true}).count();
  await page.evaluate(()=>showBoardById('industry:电池'));
  const boardDetail=await page.locator('#drawer').innerText();
  if(/资金覆盖|资金采集|主力净额/.test(boardDetail))throw new Error('板块详情仍有资金参考');
  if(!/主板成员参与/.test(boardDetail))throw new Error('板块详情未打开');
  await page.locator('#drawer').getByRole('button',{name:'×',exact:true}).click();
  await page.getByRole('button',{name:'个股',exact:true}).click();
  const stocks=await page.locator('#p-stocks').innerText();
  if(/资金三期均正|资金分区间|主力资金分位/.test(stocks))throw new Error('个股筛选仍有资金入口');
  await page.getByRole('button',{name:'总览',exact:true}).click();
  await page.screenshot({path:'output/playwright/price-only-home-20261009.png'});
  if(errors.length)throw new Error(JSON.stringify(errors));
  return {...summary,detailFundsRemoved:true,affiliationRetained:true,boardFundsRemoved:true,boardDetailFundsRemoved:true,stockFundFiltersRemoved:true,batteryMatches:battery,pageErrors:errors};
}
