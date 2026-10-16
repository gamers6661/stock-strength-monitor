async page => {
  const errors=[];
  page.on('pageerror', e=>errors.push(String(e)));
  await page.clock.install({time:new Date('2026-10-12T09:25:30+08:00')});
  await page.route('**/__status',route=>route.abort());
  await page.goto('http://127.0.0.1:8848/research/auction_board_fix_20261012/auction_replay.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  const result={};
  result.phase=await page.evaluate(()=>sessionNow());
  if(result.phase!=='竞价结束')throw Error('回放时钟不在竞价结束');
  if(!await center.getByRole('button',{name:'竞价涨幅排序',exact:true}).isVisible())throw Error('竞价排序入口缺失');
  result.defaultCards=await center.locator('.bc-card').count();
  if(!result.defaultCards)throw Error('完成日线背景筛选不能为空');
  for(const kind of ['industry','theme']){
    await center.getByRole('button',{name:kind==='industry'?'行业':'题材',exact:true}).click();
    await center.locator('[data-board-filter="all"]').click();
    const actual=await center.locator('.bc-card').evaluateAll(es=>es.map(e=>e.dataset.boardId));
    const expected=await page.evaluate(kind=>DATA.board_catalog.filter(b=>b.type===kind)
      .sort((a,b)=>{
        if(a.ranking_eligible!==b.ranking_eligible)return a.ranking_eligible?-1:1;
        if(!a.ranking_eligible)return a.name.localeCompare(b.name);
        const av=boardTodayValue(a),bv=boardTodayValue(b);
        return (av==null)-(bv==null)||(av==null?0:bv-av)||a.name.localeCompare(b.name);
      }).map(b=>b.id),kind);
    if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('竞价排序不一致 '+kind);
    result[kind+'Cards']=actual.length;
  }
  for(const [id,shown,coverage] of [['industry:房地产','-0.51%','80/80'],['theme:重组蛋白','+0.55%','17/17']]){
    const name=id.split(':')[1];
    await center.getByRole('textbox',{name:'搜索板块'}).fill(name);
    const card=center.locator('[data-board-id="'+id+'"]');
    const text=await card.innerText();
    if(!text.includes('主板成员竞价等权')||!text.includes(shown)||!text.includes(coverage))throw Error('卡片竞价数据缺失 '+id+' '+text);
    result[id]=text;
    await card.locator('.bc-name').click();
    const detail=await page.locator('#drawer').innerText();
    if(!detail.includes(shown)||!detail.includes(coverage)||!detail.includes('竞价涨幅'))throw Error('详情与卡片不一致 '+id);
    const b=await page.evaluate(id=>boardById(id),id);
    const expectedChange=b.members.find(r=>r.auction_change_pct!=null);
    const row=page.locator('#drawer tr').filter({hasText:expectedChange.code}).first();
    // Expand the full member list if this member is outside the preexisting daily lists.
    if(!await row.isVisible())await page.locator('#drawer summary').filter({hasText:'查看全部'}).click();
    if(!await row.innerText().then(t=>t.includes((expectedChange.auction_change_pct>0?'+':'')+expectedChange.auction_change_pct.toFixed(2)+'%')))throw Error('成员竞价明细不一致');
    await page.screenshot({path:'output/playwright/auction-fix-'+(id.startsWith('industry:')?'industry':'theme')+'-detail.png'});
    await page.getByRole('button',{name:'×',exact:true}).click();
    await page.screenshot({path:'output/playwright/auction-fix-'+(id.startsWith('industry:')?'industry':'theme')+'.png'});
  }
  await page.getByRole('button',{name:'题材',exact:true}).first().click();
  result.themePage=await page.locator('#theme-center').innerText();
  if(!result.themePage.includes('主板成员竞价等权'))throw Error('独立题材页未接入竞价');
  result.themePage=result.themePage.slice(0,600);
  result.smallSamples=await page.evaluate(()=>DATA.board_catalog.filter(b=>!b.member_auction.ready).length);
  await page.clock.setSystemTime(new Date('2026-10-12T09:15:30+08:00'));
  result.futureSuppressed=await page.evaluate(()=>boardAuction(boardById('industry:房地产')).ready===false);
  if(!result.futureSuppressed)throw Error('客户端显示未来竞价报价');
  await page.clock.setSystemTime(new Date('2026-10-12T09:30:30+08:00'));
  result.openBridge=await page.evaluate(()=>boardAuction(boardById('industry:房地产')).label);
  if(result.openBridge!=='主板成员竞价参考')throw Error('9:30未标注竞价参考');
  result.normalSwitch=await page.evaluate(()=>{DATA.session='早盘';return boardAuction(boardById('industry:房地产'))===null;});
  if(!result.normalSwitch)throw Error('正式盘中仍混入竞价汇总');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify(result));
}
