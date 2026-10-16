async page=>{
  const data=await page.evaluate(()=>({pane:STATE.pane,tag:document.querySelector('#ma-radar-host [data-tip]')?.outerHTML,tooltip:MS_TOOLTIP?.outerHTML,generation:DATA.ui_generation,source:DATA.ma_trend.source_at,phase:sessionNow(),tags:document.querySelectorAll('[data-tip]').length}));
  const target=page.locator('#ma-radar-host [data-tip]').first();await target.hover();
  const after=await page.evaluate(()=>({tooltip:MS_TOOLTIP?.outerHTML,target:MS_TOOLTIP_TARGET?.outerHTML,body:document.querySelector('#ms-label-tooltip')?.getBoundingClientRect().toJSON(),top:document.elementFromPoint(250,600)?.outerHTML.slice(0,250)}));
  await target.focus();const focus=await page.evaluate(()=>({tooltip:MS_TOOLTIP?.outerHTML}));
  await page.screenshot({path:'output/playwright/tooltip-debug.png',fullPage:false});return {data,after,focus};
}
