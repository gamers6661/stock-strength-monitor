async page => {
  const result = {};
  const status = await page.evaluate(async () => (await fetch('/__status',{cache:'no-store'})).json());
  result.loaded = await page.evaluate(() => ({generated:DATA.generated_at,source:(DATA.intraday_model||{}).latest_valid_quote_at,state:document.getElementById('update-state').textContent}));
  result.states = await page.evaluate(status => {
    const cases = [
      {...status, scan_active:true, scan_started_at:new Date(Date.now()-45000).toISOString()},
      {...status, scan_active:false,last_scan_ok:false,last_scan_error:'13:00 开盘后报价尚未更新：0/3120'},
      {...status, scan_active:false,last_scan_ok:false,last_scan_error:'ProxyError: 连接被拒绝'},
      {...status, scan_active:false,last_publish_ok:false,last_publish_error:'页面写入失败'}
    ];
    return cases.map(value => {renderUpdateState(value);const el=document.getElementById('update-state');return {text:el.textContent,title:el.title};});
  }, status);
  if(!result.states[0].text.startsWith('更新中 ')||result.states[1].text!=='报价待更新'||result.states[2].text!=='采集失败'||result.states[3].text!=='发布失败')throw Error('更新状态提示不正确');
  if(parseInt(result.states[0].text.slice(4),10)>60)throw Error('刷新耗时存在时区偏移');
  await page.evaluate(status => renderUpdateState(status), status);
  let injected = false;
  await page.route('**/__status', async route => {
    if(injected){await route.continue();return;}
    injected=true;
    const generated=await page.evaluate(()=>DATA.generated_at);
    const later=new Date(generated.replace(' ','T'));
    later.setSeconds(later.getSeconds()+5);
    const pad=v=>String(v).padStart(2,'0');
    const stamp=later.getFullYear()+'-'+pad(later.getMonth()+1)+'-'+pad(later.getDate())+' '+pad(later.getHours())+':'+pad(later.getMinutes())+':'+pad(later.getSeconds());
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...status,snapshot_generated_at:stamp})});
  });
  const loaded=page.waitForEvent('load',{timeout:15000});
  await page.evaluate(()=>{PAGE_VERSION=null;watchDataVersion();});
  await loaded;
  await page.unroute('**/__status');
  result.firstPollReloaded=injected;
  await page.waitForFunction(()=>!!document.getElementById('update-state')?.textContent,{timeout:15000});
  result.final=await page.evaluate(()=>({generated:DATA.generated_at,source:(DATA.intraday_model||{}).latest_valid_quote_at,fresh:document.getElementById('fresh-txt').textContent,state:document.getElementById('update-state').textContent}));
  await page.locator('header').screenshot({path:'D:/股票强势监测/output/playwright/refresh-state.png'});
  return result;
}
