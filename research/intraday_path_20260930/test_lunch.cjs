// 执行实际报价入口及实际列表渲染函数，验证午休和午后衔接。
const fs = require('fs'), vm = require('vm'), assert = require('assert'), path = require('path');
const root = path.resolve(__dirname,'../..');
const source = fs.readFileSync(path.join(root,'dashboard_template.html'),'utf8');
function fn(name, next){ return source.slice(source.indexOf('function '+name+'('),source.indexOf('function '+next+'(',source.indexOf('function '+name+'('))); }
const actual = fn('savedBoundaryQuote','auctionDisplayQuote')
  +fn('morningReferenceQuote','closeDisplayQuote')
  +fn('intradayDisplayRow','stockKeyStatus')
  +fn('attackFundText','showStock');
const date = '2026-09-30', at = date+' 12:00:00';
class FixedDate extends Date { constructor(...args){ super(...(args.length?args:[at])); } }
const sourceRow = {code:'000710', price:10.8, change_pct:9.3, intraday_quote_at:date+' 11:25:00', last_valid_quote_at:date+' 11:25:00', last_valid_price:10.8,last_valid_change_pct:9.3};
const row = {code:'000710',name:'贝瑞基因',price:10.8,change_pct:9.3,intraday_quote_at:date+' 11:25:00',live_attack_score:98.79,live_attack_stage:'反包修复',trend_tier:'A'};
function render({phase='午间休市',boundaryDay=date,boundaryPrice=10.87,missing=false,fresh=false}={}){
  const nodes={}, prices=missing?{}:{'000710':{price:boundaryPrice,change_pct:10.02,source_at:date+' 11:30:00'}};
  const ctx={Date:FixedDate,DATA:{boundary_prices:{date:boundaryDay,midday:{cutoff:'11:30',captured_at:date+' 11:31:10',prices}},attack_monitor:{rows:[row],retained:true}},
    sessionNow:()=>phase,quoteFreshAtClientNow:()=>fresh,workQuoteCurrent:()=>fresh,
    esc:String,jsq:String,fmt:(v,p)=>Number(v).toFixed(p),pct:(v,p)=>Number(v).toFixed(p)+'%',sgn:String,cls:()=>'',workProfileTags:()=>'',
    document:{getElementById:id=>nodes[id]||(nodes[id]={})}};
  vm.createContext(ctx);vm.runInContext(actual,ctx);ctx.renderAttackMonitor({'000710':sourceRow});
  return {html:nodes['work-attack-list'].innerHTML,count:nodes['work-attack-count'].textContent};
}
let result=render();
assert(result.html.includes('10.0%')&&result.html.includes('¥10.87'));
assert(result.html.includes('午间截至11:30')&&result.html.includes('判断截至 11:25'));
assert(!result.html.includes('报价已过期')&&!result.html.includes('报价待核验'));
assert(result.count.includes('11:30报价 1 只'));
result=render({missing:true});assert(result.html.includes('¥10.80')&&result.html.includes('上午最后有效报价'));assert(result.count.includes('11:30报价 0 只'));
result=render({boundaryDay:'2026-09-29',boundaryPrice:999});assert(!result.html.includes('999.00'));
result=render({boundaryPrice:-1});assert(result.html.includes('¥10.80'));
result=render({phase:'午盘'});assert(result.html.includes('午后待更新')&&result.html.includes('¥10.87'));assert(result.count.includes('午后报价待更新'));
result=render({phase:'午盘',fresh:true});assert(result.html.includes('¥10.80')&&!result.html.includes('午间截至11:30'));
console.log('PASS: 6 midday/afternoon scenarios, using actual page functions');

// 午后已取得过有效报价再发生缺失，必须优先13:05参考，不能倒退到11:30。
const retainedNodes={},last={valid:true,at:date+' 13:05:00',source_at:date+' 13:05:00',price:11,change:11.34,score:90,attack_score:98.7,attack_tier:'A',attack_stage:'反包修复',state:'当前强势',flags:[]};
const afternoonSource={...sourceRow,last_valid_quote_at:last.at,intraday_last_judgment:last};
const retainedCtx={Date:FixedDate,DATA:{boundary_prices:{date,midday:{prices:{'000710':{price:10.87,change_pct:10.02,source_at:date+' 11:30:00'}}}},attack_monitor:{rows:[{...row,reference_only:true,intraday_quote_at:last.at,intraday_judgment_at:last.at}],retained:true}},
  sessionNow:()=> '午盘',quoteFreshAtClientNow:()=>false,workQuoteCurrent:()=>true,
  esc:String,jsq:String,fmt:(v,p)=>Number(v).toFixed(p),pct:(v,p)=>Number(v).toFixed(p)+'%',sgn:String,cls:()=>'',workProfileTags:()=>'',
  document:{getElementById:id=>retainedNodes[id]||(retainedNodes[id]={})}};
vm.createContext(retainedCtx);vm.runInContext(actual,retainedCtx);
assert.equal(retainedCtx.afternoonBridgeQuote(afternoonSource),null);
retainedCtx.renderAttackMonitor({'000710':afternoonSource});
assert(retainedNodes['work-attack-list'].innerHTML.includes('¥11.00'));
assert(!retainedNodes['work-attack-list'].innerHTML.includes('¥10.87'));
assert(!retainedNodes['work-attack-list'].innerHTML.includes('暂态A'));
console.log('PASS: retained afternoon quote wins over morning boundary and is never an active candidate');

// 当前生产快照所有观察行逐只核验，不替换时间与输入。
let snap=JSON.parse(fs.readFileSync(path.join(root,'cache/snapshot.json'),'utf8'));
if(snap.session!=='午间休市')snap=JSON.parse(require('zlib').gunzipSync(fs.readFileSync(path.join(__dirname,'first_published_snapshot.json.gz'))).toString('utf8'));
const rows=snap.attack_monitor.rows,lookup=Object.fromEntries(snap.stocks.concat(snap.coverage_catalog||[]).map(r=>[r.code,r]));
const nodes={},ctx={Date:FixedDate,DATA:snap,sessionNow:()=> '午间休市',quoteFreshAtClientNow:()=>false,workQuoteCurrent:()=>false,
  esc:String,jsq:String,fmt:(v,p)=>Number(v).toFixed(p),pct:(v,p)=>Number(v).toFixed(p)+'%',sgn:String,cls:()=>'',workProfileTags:()=>'',
  document:{getElementById:id=>nodes[id]||(nodes[id]={})}};
vm.createContext(ctx);vm.runInContext(actual,ctx);ctx.renderAttackMonitor(lookup);
for(const r of rows){const q=snap.boundary_prices.midday.prices[r.code];if(q)assert(nodes['work-attack-list'].innerHTML.includes('¥'+q.price.toFixed(2)));}
assert(!nodes['work-attack-list'].innerHTML.includes('报价已过期'));
const evidence={snapshot_at:snap.generated_at,boundary_at:snap.boundary_prices.midday.captured_at,observations:rows.length,boundary_coverage:rows.filter(r=>snap.boundary_prices.midday.prices[r.code]).length,header:nodes['work-attack-count'].textContent};
fs.writeFileSync(path.join(__dirname,'render_evidence.json'),JSON.stringify(evidence,null,2),'utf8');
console.log(evidence);
