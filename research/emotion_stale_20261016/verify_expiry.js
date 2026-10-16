async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('button',{name:'情绪',exact:true}).click();
 await page.locator('#er-cap-pool').waitFor({state:'visible'});
 const before=await page.evaluate(()=>{
  MS_VIEW.emotionCaps.limit=10000;renderEmotion();
  return {generation:DATA.ui_generation,capture:DATA.quote_capture_at,expected:erModel().lists.sealed.length,
   visible:document.querySelectorAll('#er-cap-pool [data-cap-code]').length,fresh:erLive(),
   promotion:(erModel().promotion.find(p=>p.sealed>0)||{}).height};
 });
 if(!before.expected||before.visible!==before.expected||!before.fresh)throw Error('Missing live starting frame '+JSON.stringify(before));
 if(before.promotion!=null){
  await page.locator('[data-promotion-height="'+before.promotion+'"]').click();
  await page.locator('#er-promotion-list').waitFor({state:'visible'});
 }
 try{
  const expired=await page.evaluate(()=>{
   const rows=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]);
   const until=rows.map(r=>r.emotion_relay).filter(m=>m&&m.valid&&m.valid_until).map(m=>parseDT(m.valid_until).getTime());
   window.__expiryOriginalNow=Date.now;Date.now=()=>Math.max.apply(null,until)+1000;
   refreshPageFreshness();renderEmotion();
   const pool=document.getElementById('er-cap-pool'),drawer=document.getElementById('drawer');
   return {generation:DATA.ui_generation,fresh:erLive(),visible:pool.querySelectorAll('[data-cap-code]').length,
    warning:!!document.querySelector('#emotion-host .er-retained-notice'),currentLabels:pool.innerText.includes('当前涨停'),
    lastRecorded:pool.innerText.includes('上次封板'),promotionReference:!drawer.classList.contains('open')||drawer.innerText.includes('上次晋级记录')};
  });
  if(expired.generation!==before.generation)throw Error('Generation changed during controlled expiry');
  if(expired.fresh||!expired.warning||expired.currentLabels||!expired.lastRecorded||expired.visible!==before.expected||!expired.promotionReference)
   throw Error('Expiry did not retain explicit history '+JSON.stringify(expired));
  if(await page.locator('#drawer.open').count())await page.locator('#dr-x').click();
  await page.locator('#er-cap-pool').scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/emotion-expired-retained.png',fullPage:false});
  await page.evaluate(()=>{Date.now=window.__expiryOriginalNow;delete window.__expiryOriginalNow;refreshPageFreshness();renderEmotion();});
  const restored=await page.evaluate(()=>({generation:DATA.ui_generation,fresh:erLive(),retained:erHasRetained(),
   warning:!!document.querySelector('#emotion-host .er-retained-notice'),expected:erModel().lists.sealed.length,
   visible:document.querySelectorAll('#er-cap-pool [data-cap-code]').length}));
  if(!restored.fresh||restored.warning!==restored.retained||restored.visible!==restored.expected)
   throw Error('Current frame did not restore '+JSON.stringify(restored));
  if(errors.length)throw Error(errors.join('\n'));
  return {before,expired,restored,errors};
 }finally{
  await page.evaluate(()=>{if(window.__expiryOriginalNow){Date.now=window.__expiryOriginalNow;delete window.__expiryOriginalNow;refreshPageFreshness();renderEmotion();}});
 }
}
