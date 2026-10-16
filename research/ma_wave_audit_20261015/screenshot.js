async (page) => {
 await page.getByRole('button',{name:'×',exact:true}).click();
 await page.getByRole('button',{name:'选股雷达',exact:true}).click();
 await page.getByRole('combobox',{name:'趋势观察范围',exact:true}).selectOption('all');
 await page.getByRole('combobox',{name:'均线阶段',exact:true}).selectOption('');
 await page.locator('#ma-radar-host [data-strength-id="000995"]').scrollIntoViewIfNeeded();
 await page.screenshot({path:'output/playwright/huangtai-historical-origin.png',fullPage:false});
 return {shown:await page.locator('#ma-radar-host [data-strength-id="000995"]').innerText()};
}
