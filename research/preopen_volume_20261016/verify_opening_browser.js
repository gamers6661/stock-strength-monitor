async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 if(await page.locator('#drawer.open').count())await page.locator('#dr-x').click();
 const info=await page.evaluate(()=>({version:DATA.ui_generation,session:DATA.session,capture:DATA.quote_capture_at,ref:DATA.reference_view||null}));
 if(info.session!=='早盘'||info.ref)throw Error('Opening did not leave completed reference mode');
 await page.evaluate(()=>showStock('001246'));
 await page.locator('#k-cv').waitFor({state:'visible'});await page.waitForFunction(()=>MS_CHART&&MS_CHART.bars);
 const badge=await page.locator('.ma-detail-badge').innerText();
 if(!badge.includes('有效样本观察')||badge.includes('快照已过期')||badge.includes('待核验'))throw Error('Short-history badge '+badge);
 const bars=await page.evaluate(()=>MS_CHART.bars.map(b=>b.date));if(bars.at(-1)!=='2026-10-16')throw Error('Missing latest observed candle');
 await page.screenshot({path:'output/playwright/opening-short-history.png',fullPage:false});
 await page.locator('#dr-x').click();if(errors.length)throw Error(errors.join('\n'));
 return {info,badge,candles:bars.length,last:bars.at(-1),errors};
}
