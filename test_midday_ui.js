// Regression checks for live chart projection and the 11:30/lunch boundary.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
function fn(file,name){const t=fs.readFileSync(file,'utf8'),start=t.indexOf('function '+name+'(');assert(start>=0);let b=t.indexOf('{',start),depth=1,i=b+1;for(;depth;i++){if(t[i]==='{')depth++;if(t[i]==='}')depth--;}return t.slice(start,i);}
let clock='2026-10-22T12:00:00',phase='午间休市';
const RealDate=Date;
class TestDate extends Date{constructor(...a){super(...(a.length?a:[clock]));}static now(){return new RealDate(clock).getTime();}}
const ctx={Date:TestDate,DATA:{},sessionNow:()=>phase,msReferenceDay:()=>null,parseDT:s=>s?new TestDate(s):null};
vm.createContext(ctx);
vm.runInContext(fn('ma_trend_ui.js','mtSnapshotFresh')+'\n'+fn('stock_selection_ui.js','ssChartBars'),ctx);
let checks=0;
function check(v,msg){assert(v,msg);checks++;}
const morning={mode:'连续竞价',quote_at:'2026-10-22 11:30:00',valid_until:'2026-10-22 11:40:00'};
check(ctx.mtSnapshotFresh(morning),'same-day boundary retained at noon');
check(!ctx.mtSnapshotFresh({...morning,quote_at:'2026-10-21 11:30:00'}),'yesterday not revived');
check(!ctx.mtSnapshotFresh({...morning,quote_at:'2026-10-22 11:25:00'}),'missed boundary not revived');
check(!ctx.mtSnapshotFresh({...morning,reference_only:true}),'reference-only not promoted');
phase='午盘';clock='2026-10-22T13:00:01';
check(!ctx.mtSnapshotFresh(morning),'morning stops at afternoon open');
check(!ctx.mtSnapshotFresh({...morning,mode:'午休参考',valid_until:'2026-10-22 13:00:00'}),'lunch stops at afternoon open');
phase='早盘';clock='2026-10-22T11:35:00';
check(ctx.mtSnapshotFresh(morning),'normal freshness preserved');
clock='2026-10-22T12:00:00';phase='午间休市';
const rows=process.argv[2]?JSON.parse(fs.readFileSync(process.argv[2],'utf8')):[];
const result={rows:rows.length,selection:0,today_candles:0,history_only:[],ma_current_before:0,ma_current_after:0,relay_valid:0,relay_noon_fresh:0};
for(const {code,s,x} of rows){
 const m=s.ma_trend||{};
 if(m.eligible){if(new RealDate(m.valid_until)>=new RealDate(clock))result.ma_current_before++;if(ctx.mtSnapshotFresh(m))result.ma_current_after++;}
 const er=s.emotion_relay||{};
 if(er.valid&&!er.suspended_current){result.relay_valid++;if(ctx.mtSnapshotFresh({mode:er.mode==='盘中暂态'?'连续竞价':er.mode,quote_at:er.quote_at,valid_until:er.valid_until}))result.relay_noon_fresh++;}
 if(!x)continue;result.selection++;
 const bars=ctx.ssChartBars(s,x),last=bars.at(-1);
 if(last&&last.date==='2026-10-22')result.today_candles++;else result.history_only.push({code,chart_source:s.chart_source,last:last&&last.date});
 if(s.chart_source==='quoted_ohlc'&&String(s.chart_at).startsWith('2026-10-22')){
  check(last&&last.date==='2026-10-22',code+' current candle hidden');
  const original=s.chart_history.at(-1);
  check(JSON.stringify(last)===JSON.stringify(original),code+' candle changed');
 }
 check(bars.every(b=>b.date<='2026-10-22'),code+' future candle');
}
const b={date:'2026-10-22',open:1,high:2,low:1,close:2};
const current={chart_source:'quoted_ohlc',chart_at:'2026-10-22 11:30:00',chart_history:[{date:'2026-10-21',open:1,high:2,low:1,close:1.5},b]};
const selection={daily_at:'2026-10-21',quote:{at:'2026-10-22 11:30:00'}};
check(ctx.ssChartBars(current,selection).at(-1)===b,'validated live candle retained');
check(ctx.ssChartBars({...current,chart_at:'2026-10-21 11:30:00'},selection).length===1,'mismatched quote day rejected');
check(ctx.ssChartBars({...current,chart_history:[{...b,high:1}]},selection).length===0,'invalid OHLC rejected');

check(ctx.ssChartBars({chart_source:'completed_daily_history',chart_history:[b]},{daily_at:'2026-10-21',quote:{at:'2026-10-22'}}).length===0,'unverified live candle rejected');
for(const source of ['completed_daily_history','formal_daily']){
 check(ctx.ssChartBars({chart_source:source,chart_at:'2026-10-22',chart_history:[b]},selection).at(-1)===b,'verified display day independent of scoring day: '+source);
}
result.checks=checks;
if(process.argv[3])fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2));
console.log(JSON.stringify(result));
