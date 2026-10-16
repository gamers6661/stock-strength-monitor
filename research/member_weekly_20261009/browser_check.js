async page => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/__status',r=>r.abort());
  await page.goto('http://127.0.0.1:8848/research/member_weekly_20261009/preview.html');
  await page.getByRole('button',{name:'板块',exact:true}).click();
  const center=page.locator('#board-center');
  await center.getByRole('textbox').fill('电池');
  const card=center.locator('[data-board-id="industry:电池"]');
  const text=await card.innerText();
  if(text.includes('成员待更新')||!text.includes('成员缓存'))throw Error('member badge wrong');
  await card.getByRole('button',{name:'成员缓存，查看注释',exact:true}).click();
  const note=await page.locator('#ui-note-tip').innerText();
  if(!note.includes('7天')||!note.includes('未完整'))throw Error('cache provenance hidden');
  await page.keyboard.press('Escape');
  await center.getByRole('button',{name:'成员每周更新，查看注释',exact:true}).click();
  const weeklyNote=await page.locator('#ui-note-tip').innerText();
  if(!weeklyNote.includes('2026-10-16 15:15:00'))throw Error('weekly date wrong');
  const meta=await page.evaluate(()=>({policy:DATA.member_refresh,index:DATA.board_catalog.find(b=>b.id==='industry:电池').index_current}));
  if(!meta.index.ready)throw Error('index path broken');
  await page.keyboard.press('Escape');
  await page.screenshot({path:'output/playwright/member-weekly.png'});
  if(errors.length)throw Error(errors.join(';'));
  return {card:text,note,weeklyNote,policy:meta.policy,indexQuote:meta.index.quote_at,pageErrors:errors};
}
