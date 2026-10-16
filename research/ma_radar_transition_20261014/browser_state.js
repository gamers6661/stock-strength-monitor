async page=>{
 return await page.evaluate(()=>({pane:STATE.pane,shown:Array.from(document.querySelectorAll('.pane.on')).map(e=>e.id),tag:document.querySelector('#ma-radar-host [data-tip]')?.outerHTML,tooltip:MS_TOOLTIP?.outerHTML,generation:DATA.ui_generation,source:DATA.ma_trend.source_at,phase:sessionNow(),tags:document.querySelectorAll('[data-tip]').length,url:location.href,nav:Array.from(document.querySelectorAll('#seg button')).map(e=>({text:e.textContent,pane:e.dataset.p,class:e.className})),radarBox:document.getElementById('p-radar').getBoundingClientRect().toJSON()}));
}
