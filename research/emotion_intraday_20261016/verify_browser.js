async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 if(await page.locator('#drawer.open').count())await page.locator('#dr-x').click();
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 await page.locator('#er-cap-pool').waitFor({state:'visible'});
 const result=await page.evaluate(()=>{
  const meta=erModel(),by={};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(r=>by[r.code]=r);
  const caps=meta.lists.sealed.map(c=>by[c].emotion_relay);
  const pool=document.querySelector('#er-cap-pool');
  return {generation:DATA.ui_generation,capture:DATA.quote_capture_at,mode:meta.mode,
   caps:caps.length,verified:caps.filter(m=>m.cap_strength.verified).length,
   ranked:pool.querySelectorAll('.er-pool-rank').length,body:pool.innerText,
   onePrice:caps.filter(m=>m.risks.includes('一字板')).length,
   invalidHeights:caps.filter(m=>m.height_exact&&m.height!==(m.prior_height||0)+1).map(m=>m.code),
   promotions:meta.promotion.map(p=>({height:p.height,success:p.sealed,ids:p.success_codes}))};
 });
 if(!result.caps||!result.verified||!result.ranked)throw Error('Missing live strength '+JSON.stringify(result));
 if(result.invalidHeights.length)throw Error('Invalid live height');
 for(const text of ['在板待收盘','当前在板，待收盘确认','一字价格区间','成交受限','明细待补齐']){
  if(result.body.includes(text))throw Error('Unexpected label '+text);
 }
 if(!result.onePrice||!result.body.includes('一字板'))throw Error('Missing one-price label');
 await page.locator('#er-cap-pool').scrollIntoViewIfNeeded();
 await page.screenshot({path:'output/playwright/emotion-live-caps.png',fullPage:false});
 const promotion=page.locator('[data-promotion-height="1"]');
 if(await promotion.count()){
  await promotion.click();await page.locator('#er-promotion-list').waitFor({state:'visible'});
  if((await page.locator('#drawer').innerText()).includes('在板待确认'))throw Error('Promotion still waits for close');
  await page.locator('#dr-x').click();
 }
 if(errors.length)throw Error(errors.join('\n'));
 delete result.body;return {...result,errors};
}
