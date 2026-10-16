async (page) => {
  const out='D:/股票强势监测/research/market_strength_v1_20261013/rework_3/frozen-browser';
  await page.goto('http://127.0.0.1:8848/research/market_strength_v1_20261013/rework_3/frozen_dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).waitFor();
  const generation=await page.evaluate(()=>DATA.ui_generation);
  const results={generation,exports:[],members:[]};
  async function download(key,label){
    const pending=page.waitForEvent('download');
    await page.locator(key==='radar'?'#radar-opportunities':key==='industry'?'#board-center':'#theme-center').getByRole('button',{name:'导出全部筛选结果 CSV',exact:true}).click();
    const file=await pending;await file.saveAs(out+'/'+label+'.csv');
    results.exports.push({key,label,file:file.suggestedFilename(),ids:await page.evaluate(k=>msRows(k).map(r=>r.id||r.code),key)});
  }
  for(const [key,label,host] of [['industry','板块','#board-center'],['theme','题材','#theme-center']]){
    await page.getByRole('button',{name:label,exact:true}).click();
    await download(key,key+'-before');
    const ids=await page.evaluate(k=>msRows(k).map(r=>r.id),key);
    for(let i=0;i<Math.min(3,ids.length);i++){
      await page.locator(host+' [data-strength-id]').filter({has:page.locator('td')}).nth(i).click();
      await page.getByRole('button',{name:'在个股页查看该板块全部成员',exact:true}).waitFor();
      await page.locator('#dr-x').click();
      if(i===0)await download(key,key+'-one');
    }
    await download(key,key+'-many');
  }
  for(const [key,label,host,name] of [['theme','题材','#theme-center','染料'],['industry','板块','#board-center','影视院线']]){
    await page.getByRole('button',{name:label,exact:true}).click();
    await page.locator(host+' [aria-label="强势范围"]').selectOption('all');
    await page.locator(host+' [aria-label="强势搜索"]').fill(name);
    await page.locator(host+' [data-strength-id]').first().click();
    await page.getByRole('button',{name:'在个股页查看该板块全部成员',exact:true}).click();
    await page.locator('#ms-stock-host').waitFor();
    const initial=await page.evaluate(()=>({id:STATE.boardFilterId,scope:MS_VIEW.stocks.scope,phase:MS_VIEW.stocks.phase,q:MS_VIEW.stocks.q,limit:MS_VIEW.stocks.limit,ids:msRows('stocks').map(r=>r.code),expected:boardById(STATE.boardFilterId).member_codes.filter(c=>msModel().stocks.all.includes(c)),order:msModel().stocks.sorts.combined}));
    if(initial.scope!=='all'||initial.q||initial.phase||initial.limit!==100||JSON.stringify(initial.ids)!==JSON.stringify(initial.order.filter(c=>initial.expected.includes(c))))throw new Error('Member entry mismatch '+name);
    const subsets={};
    for(const axis of ['trend','emotion']){
      await page.locator('#ms-stock-host [aria-label="强势范围"]').selectOption(axis);
      await page.locator('#ms-stock-host [aria-label="强势排序"]').selectOption(axis);
      const v=await page.evaluate(a=>({ids:msRows('stocks').map(r=>r.code),expected:msModel().stocks.sorts[a].filter(c=>boardById(STATE.boardFilterId).member_codes.includes(c)&&msModel().stocks[a].includes(c))}),axis);
      if(JSON.stringify(v.ids)!==JSON.stringify(v.expected))throw new Error('Member subset mismatch '+axis);
      subsets[axis]=v.ids;
    }
    await page.locator('#ms-stock-host [aria-label="强势范围"]').selectOption('all');
    await page.locator('#ms-stock-host [data-strength-id]').first().click();
    await page.locator('#dr-b').getByText('统一市场强度',{exact:true}).waitFor();
    if(!(await page.locator('#dr-b').innerText()).includes(generation))throw new Error('Member detail generation mismatch');
    await page.screenshot({path:out+'/'+key+'-member-detail.png'});
    await page.locator('#dr-x').click();
    await page.getByRole('button',{name:'清除成员筛选',exact:true}).click();
    const cleared=await page.evaluate(()=>({id:STATE.boardFilterId,scope:MS_VIEW.stocks.scope,ids:msRows('stocks').map(r=>r.code),expected:msModel().stocks.sorts.combined}));
    if(cleared.id!==null||cleared.scope!=='all'||JSON.stringify(cleared.ids)!==JSON.stringify(cleared.expected))throw new Error('Member clear failed');
    results.members.push({name,id:initial.id,count:initial.ids.length,all:initial.ids,subsets,clear_count:cleared.ids.length,detail_generation:generation});
  }
  await page.getByRole('button',{name:'选股雷达',exact:true}).click();
  await download('radar','stocks-browser');
  if(await page.evaluate(()=>DATA.ui_generation)!==generation)throw new Error('Generation changed during verification');
  await page.screenshot({path:out+'/radar.png'});
  return results;
}
