// 执行实际展示入口及关键状态函数：午休、缺失、跨日和午后更新。
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'dashboard_template.html'),'utf8');
const code=source.slice(source.indexOf('function intradayDisplayRow('),source.indexOf('function renderStocks('));
class FixedDate extends Date {constructor(...args){super(...(args.length?args:['2026-09-30T12:15:00']));}}
let phase='午间休市',fresh=false;
const ctx={Date:FixedDate,quoteFreshAtClientNow:()=>fresh,sessionNow:()=>phase,
  useCompletedClose:()=>false,afternoonBridgeQuote:()=>null,morningOpenBridgeQuote:()=>null};
vm.createContext(ctx);vm.runInContext(code,ctx);
const row={code:'000710',intraday_observation_available:true,intraday_judgment_at:'2026-09-30 11:30:00',
  intraday_score:85,live_attack_score:99,live_attack_tier:'A',intraday_risk_flags:[],
  intraday_path:{state:'扫描失守后收复 · 守线3次'}};
assert.equal(ctx.intradayDisplayRow(row).intraday_score,85);
assert(ctx.stockKeyStatus(row,false,null).label.includes('上午截至11:30 · 扫描失守后收复'));
const lost={...row,intraday_observation_available:false,intraday_score:null,
  intraday_last_judgment:{valid:true,at:'2026-09-30 11:30:00',score:85,attack_score:99,attack_tier:'A',state:'封板状态',risk:'提示',flags:['一字涨停']}};
assert.equal(ctx.intradayDisplayRow(lost).live_attack_tier,'A');
assert(ctx.stockKeyStatus(lost,false,null).label.includes('最近有效判断'));
const yesterday={...lost,intraday_last_judgment:{...lost.intraday_last_judgment,at:'2026-09-29 11:30:00'}};
assert.equal(ctx.intradayDisplayRow(yesterday),null);
phase='午盘';fresh=true;
const afternoon={...row,intraday_judgment_at:'2026-09-30 13:05:00',intraday_score:66};
assert.equal(ctx.intradayDisplayRow(afternoon).intraday_score,66);
assert(!ctx.stockKeyStatus(afternoon,true,null).label.includes('上午截至'));
fresh=false;
assert(ctx.stockKeyStatus(lost,false,null).label.includes('截至11:30'));
console.log('PASS: 6 actual status rendering scenarios');

const snap=JSON.parse(fs.readFileSync(path.join(root,'cache/snapshot.json'),'utf8'));
phase=snap.session;ctx.Date=Date;
const rows=snap.stocks.concat(snap.coverage_catalog||[]),available=rows.filter(r=>r.intraday_observation_available===true);
if(available.length){
  assert(available.every(r=>ctx.intradayDisplayRow(r)));
  assert(available.every(r=>ctx.stockKeyStatus(r,false,null).label.includes((phase==='午间休市'?'上午截至':'截至')+r.intraday_judgment_at.slice(11,16))));
  const evidence={snapshot_at:snap.generated_at,available:available.length,
    scored:available.filter(r=>r.intraday_score!=null).length,graded:available.filter(r=>r.live_attack_tier!=null).length,
    examples:rows.filter(r=>['000710','002962','603231'].includes(r.code)).map(r=>({code:r.code,score:r.intraday_score,attack:r.live_attack_score,tier:r.live_attack_tier,status:ctx.stockKeyStatus(r,false,null).label,path:r.intraday_path}))};
  fs.writeFileSync(path.join(__dirname,phase==='午间休市'?'status_render_evidence.json':'afternoon_status_render_evidence.json'),JSON.stringify(evidence,null,2));
  console.log({snapshot_at:evidence.snapshot_at,available:evidence.available,scored:evidence.scored,graded:evidence.graded});
}
