const fs=require('fs'),vm=require('vm'),zlib=require('zlib');
const html=fs.readFileSync('dashboard_template.html','utf8');
const start=html.indexOf('function exportCSV(){'),end=html.indexOf('\nfunction ',start+1);
const snapshot=JSON.parse(zlib.gunzipSync(fs.readFileSync(process.argv[2]||'research/consolidation_ma20_20261008/live_snapshot.json.gz')));
let exported;
const sandbox={DATA:snapshot,STOCK_VIEW:'all',stockViewRows:()=>snapshot.stocks.concat(snapshot.coverage_catalog||[]),
 quoteFreshAtClientNow:r=>r.intraday_quote_fresh,quoteStatusAtClientNow:r=>r.intraday_quote_status,
 currentCandidateActive:(r,k)=>!!r[k],afternoonBridgeQuote:()=>null,morningOpenBridgeQuote:()=>null,
 auctionDisplayQuote:()=>null,lunchDisplayQuote:()=>null,useCompletedClose:()=>false,closeDisplayQuote:()=>null,
 Blob:class{constructor(parts){exported=parts.join('');}},URL:{createObjectURL:()=>''},
 document:{createElement:()=>({click:()=>{}})},toast:()=>{}};
vm.createContext(sandbox);vm.runInContext(html.slice(start,end)+'\nexportCSV();',sandbox);
fs.writeFileSync('research/consolidation_ma20_20261008/导出验收.csv',exported,'utf8');
console.log('实际导出函数已运行，输出 '+sandbox.stockViewRows().length+' 条');
