async page => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/__status',r=>r.abort());
  await page.goto('http://127.0.0.1:8848/dashboard.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const result=await page.evaluate(()=>{
    const indexes=DATA.board_catalog.filter(b=>b.index_current);
    return {total:indexes.length,ready:indexes.filter(b=>b.index_current.ready).length,
      errors:indexes.filter(b=>b.index_current.fetch_error).map(b=>b.name),
      quoteTimes:[...new Set(indexes.map(b=>b.index_current.quote_at))].sort(),
      health:DATA.data_sources.ths_index_quotes};
  });
  if(result.total!==450||result.ready!==450||result.errors.length)throw Error(JSON.stringify(result));
  const center=page.locator('#board-center');
  await center.getByRole('textbox').fill('电池');
  const card=await center.locator('[data-board-id="industry:电池"]').innerText();
  if(/更新受限|指数待更新/.test(card))throw Error('battery still pending');
  await page.screenshot({path:'output/playwright/board-refresh-live.png'});
  if(errors.length)throw Error(errors.join(';'));
  return {...result,card,pageErrors:errors};
}

