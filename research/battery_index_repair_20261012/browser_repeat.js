async page => {
 await page.reload();
 await page.getByRole('button',{name:'板块',exact:true}).click();
 await page.locator('#board-center').getByRole('textbox',{name:'搜索板块'}).fill('电池');
 const result=await page.evaluate(()=>({generated_at:DATA.generated_at,version:DATA.board_trend_model.version,ready:DATA.board_trend_model.current_ready,pending:DATA.board_trend_model.current_pending,revalidation:DATA.board_trend_model.history_revalidation,battery:boardById('industry:电池').index_current}));
 if(result.ready!==450||result.pending!==0||!result.battery.ready||result.revalidation.needed!==0)throw Error(JSON.stringify(result));
 result.card=await page.locator('#board-center [data-board-id="industry:电池"]').innerText();
 if(result.card.includes('指数待更新'))throw Error('后续刷新仍待更新');
 return result;
}
