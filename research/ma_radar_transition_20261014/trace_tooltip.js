async page=>{
 await page.evaluate(()=>{window.TIP_TRACE=[];for(const name of ['mouseover','mouseout','scroll','focusout'])document.addEventListener(name,e=>TIP_TRACE.push({name,target:e.target.tagName,cls:String(e.target.className),related:e.relatedTarget&&e.relatedTarget.tagName,tip:MS_TOOLTIP?.hidden}),true);const original=msHideTooltip;msHideTooltip=function(){TIP_TRACE.push({hide:Error().stack.split('\n').slice(1,4)});return original();};});
 await page.getByRole('button',{name:'个股',exact:true}).hover();
 const target=page.locator('#ms-stock-host .ms-tag[data-tip]').first();await target.hover();
 return await page.evaluate(()=>({trace:TIP_TRACE.slice(-18),tooltip:MS_TOOLTIP?.outerHTML}));
}
