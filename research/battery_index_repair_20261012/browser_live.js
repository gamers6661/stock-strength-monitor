async page => {
 const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8848/dashboard.html');
 await page.getByRole('button',{name:'板块',exact:true}).click();
 const center=page.locator('#board-center');
 await center.getByRole('textbox',{name:'搜索板块'}).fill('电池');
 const card=center.locator('[data-board-id="industry:电池"]');
 const result=await page.evaluate(()=>{
  const b=boardById('industry:电池');
  return {generated_at:DATA.generated_at,version:DATA.board_trend_model.version,
    current_ready:DATA.board_trend_model.current_ready,current_pending:DATA.board_trend_model.current_pending,
    history_revalidation:DATA.board_trend_model.history_revalidation,
    battery:{daily:b.index_trend,current:b.index_current,quote:b.index_quote}};
 });
 if(result.version!=='板块实时趋势4'||!result.battery.current.ready)throw Error('实际页面电池未恢复：'+JSON.stringify(result));
 if(Math.abs(result.battery.daily.close-result.battery.quote.previous_close)>.01)throw Error('电池昨收未对齐');
 result.card=await card.innerText();
 if(result.card.includes('指数待更新'))throw Error('电池卡片仍待更新');
 await page.screenshot({path:'output/playwright/battery-index-fixed-card.png'});
 await card.locator('.bc-name').click();
 await page.getByRole('heading',{name:'主板成员参与',exact:true}).waitFor();
 result.detail=await page.locator('#drawer').innerText();
 if(result.detail.includes('指数待更新'))throw Error('电池详情仍待更新');
 await page.screenshot({path:'output/playwright/battery-index-fixed-detail.png'});
 if(errors.length)throw Error(errors.join('\n'));
 return result;
}
