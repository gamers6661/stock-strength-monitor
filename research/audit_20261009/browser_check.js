async (page) => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.waitForFunction(()=>typeof DATA!=='undefined'&&document.getElementById('update-state').textContent==='已同步');
  const overview=await page.evaluate(()=>({date:DATA.strength_model.asof,
    closeDate:DATA.close_strong_board.asof,pending:DATA.close_strong_board.today_pending,
    selected:document.querySelector('#work-switch button.on').dataset.work,
    mode:WORK_MODE,closeCount:DATA.close_strong_board.count,
    kernelState:document.getElementById('update-state').textContent,
    refreshDisabled:document.getElementById('btn-refresh').disabled,
    brokenPriceFactors:DATA.stocks.filter(s=>s.factors.rs!==s.score||s.factors.sector!==s.industry_breadth).length}));
  if(overview.date!=='2026-10-09'||overview.closeDate!==overview.date||overview.pending
    ||overview.mode!=='close'||overview.selected!=='close'||overview.brokenPriceFactors
    ||overview.kernelState!=='已同步'||overview.refreshDisabled)throw new Error(JSON.stringify(overview));
  await page.screenshot({path:'output/playwright/audit-home-20261009.png'});
  await page.locator('#work-close-table tbody tr').first().click();
  await page.locator('#drawer summary').filter({hasText:'归属与数据来源'}).click();
  const detail=await page.locator('#drawer').innerText();
  if(!/归属与数据来源/.test(detail)||/历史资金|主力净额|超大单净额/.test(detail))throw new Error('详情口径不正确');
  await page.locator('#drawer').getByRole('button',{name:'×',exact:true}).click();
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const boards=await page.evaluate(()=>({names:DATA.board_catalog.filter(b=>b.type==='industry').map(b=>b.name),
    battery:DATA.board_catalog.find(b=>b.id==='industry:电池').index_current}));
  if(!boards.names.includes('种植业与林业')||!boards.battery||boards.battery.asof!==overview.date)throw new Error('行业目录或当日指数判断丢失');
  await page.evaluate(()=>showBoardById('industry:电池'));
  const boardDetail=await page.locator('#drawer').innerText();
  if(/主力净额|资金覆盖/.test(boardDetail)||!boardDetail.includes('电池'))throw new Error('板块详情口径错误');
  await page.screenshot({path:'output/playwright/audit-battery-20261009.png'});
  await page.locator('#drawer').getByRole('button',{name:'×',exact:true}).click();
  await page.getByRole('button',{name:'个股',exact:true}).click();
  await page.locator('#q').fill('时代万恒');
  await page.waitForFunction(()=>STATE.q==='时代万恒');
  if(!await page.locator('#tb-stocks').innerText().then(t=>t.includes('600241')))throw new Error('中文检索失效');
  await page.locator('#q').fill('');
  await page.waitForFunction(()=>STATE.q==='');
  const exports=await page.evaluate(async()=>{
    async function capture(fn){let blob;const u=URL.createObjectURL,c=HTMLAnchorElement.prototype.click;
      try{URL.createObjectURL=b=>(blob=b,'blob:audit');HTMLAnchorElement.prototype.click=function(){};fn();}
      finally{URL.createObjectURL=u;HTMLAnchorElement.prototype.click=c;}
      return (await blob.text()).trim().split(/\r?\n/);}
    const lines=await capture(exportCSV),close=await capture(exportCloseBoard);
    const codes=lines=>lines.slice(1).map(l=>l.match(/^"([^"]*)"/)[1]);
    function width(line){let q=false,n=1;for(let i=0;i<line.length;i++){if(line[i]==='"'){if(q&&line[i+1]==='"'){i++;continue;}q=!q;}else if(line[i]===','&&!q)n++;}return n;}
    return {rows:lines.length-1,columns:width(lines[0]),
      rectangular:lines.every(l=>width(l)===width(lines[0])),
      stockParity:JSON.stringify(codes(lines))===JSON.stringify(stockViewRows('all',true).map(s=>s.code)),
      closeParity:JSON.stringify(codes(close))===JSON.stringify(DATA.close_strong_board.stocks.map(s=>s.code)),
      noFunds:!/资金流|超大单|主力净额/.test(lines[0])};
  });
  if(!exports.rectangular||!exports.stockParity||!exports.closeParity||!exports.noFunds)throw new Error(JSON.stringify(exports));
  await page.getByRole('button',{name:'总览',exact:true}).click();
  if(errors.length)throw new Error(JSON.stringify(errors));
  return {overview,exports,batteryState:boards.battery.state,batteryQuoteAt:boards.battery.quote_at,
    industryCount:boards.names.length,plantingAndForestry:true,detailSourcesRetained:true,chineseSearch:true,pageErrors:errors};
}
