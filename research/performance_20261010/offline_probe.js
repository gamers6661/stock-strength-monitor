async (page) => {
  const base='http://127.0.0.1:8848';
  await page.unroute('**/__status');
  await page.goto(base+'/dashboard.html');
  await page.waitForFunction(()=>DATA.ui_lazy);
  await page.getByRole('button',{name:'个股',exact:true}).click();
  const [download]=await Promise.all([
    page.waitForEvent('download'),page.getByRole('button',{name:'完整离线看板',exact:true}).click()
  ]);
  await download.saveAs('D:/股票强势监测/research/performance_20261010/offline.html');
  await page.goto('file:///D:/股票强势监测/research/performance_20261010/offline.html');
  await page.waitForFunction(()=>DATA.stocks&&DATA.stocks.length===3024);
  const requests=[];page.on('request',r=>requests.push(r.url()));
  const result=await page.evaluate(async()=>{
    await showStock('600241');let s=stockPoolRows().find(s=>s.code==='600241');
    const stock={chart:!!s.k&&!!document.getElementById('k-cv'),path:!!s.intraday_path.recent,themes:!!s.theme_relations.length};
    await showBoardById('industry:电池');let b=boardById('industry:电池');
    let blob,oldURL=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;
    URL.createObjectURL=b=>{blob=b;return 'blob:offline';};HTMLAnchorElement.prototype.click=function(){};
    try{await exportCSV();}finally{URL.createObjectURL=oldURL;HTMLAnchorElement.prototype.click=oldClick;}
    return {stock,board:b.members.every(r=>!!r.name),pool:stockPoolRows().length,
      lazy:!!DATA.ui_lazy,csvColumns:(await blob.text()).split('\n')[0].split(',').length,
      hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))).map(x=>x.toString(16).padStart(2,'0')).join('')};
  });
  result.networkRequests=requests;return result;
}
