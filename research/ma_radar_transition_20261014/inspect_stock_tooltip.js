async page=>{
 await page.getByRole('button',{name:'个股',exact:true}).click();
 const target=page.locator('#ms-stock-host .ms-tag[data-tip]').first();await target.hover();
 const after=await target.evaluate(el=>{const box=el.getBoundingClientRect();return {tag:el.outerHTML,box:box.toJSON(),hit:document.elementFromPoint(box.x+box.width/2,box.y+box.height/2)?.outerHTML.slice(0,500),tooltip:MS_TOOLTIP?.outerHTML,tipbox:MS_TOOLTIP?.getBoundingClientRect().toJSON(),pane:STATE.pane};});
 await target.focus();const focus=await page.evaluate(()=>({tooltip:MS_TOOLTIP?.outerHTML}));await page.screenshot({path:'output/playwright/tooltip-debug.png',fullPage:false});return {after,focus};
}
