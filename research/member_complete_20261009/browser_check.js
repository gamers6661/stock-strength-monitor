async page => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/__status',r=>r.abort());
  await page.goto('http://127.0.0.1:8848/research/member_complete_20261009/preview.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  const results=[];
  for(const [name,count] of [['电池',107],['种植业与林业',29],['化学制药',159]]){
    await center.getByRole('textbox').fill(name);
    const card=center.locator('[data-board-id="industry:'+name+'"]');
    const cardText=await card.innerText();
    if(/成员缓存|成员待更新/.test(cardText))throw Error(name+' still incomplete');
    await card.getByRole('button',{name,exact:true}).click();
    await page.getByText('数据与判断依据',{exact:true}).click();
    const detail=await page.locator('.detail-fold[open]').innerText();
    if(!detail.includes('完整源成员 '+count+'只')||!detail.includes('完整成员接口'))throw Error(name+' count/source wrong');
    results.push({name,count,card:cardText,source:detail.split('\n').find(s=>s.includes('成员来源'))});
    await page.keyboard.press('Escape');
  }
  const meta=await page.evaluate(()=>({version:DATA.board_catalog_version,policy:DATA.member_refresh,official:DATA.board_catalog.filter(b=>b.type==='industry'&&b.catalog_listed).map(b=>({name:b.name,stale:b.membership_stale}))}));
  if(meta.official.length!==90||meta.official.some(b=>b.stale))throw Error('official industry incomplete');
  if(errors.length)throw Error(errors.join(';'));
  await page.screenshot({path:'output/playwright/member-complete.png'});
  return {results,version:meta.version,policy:meta.policy,industries:meta.official.length,pageErrors:errors};
}
