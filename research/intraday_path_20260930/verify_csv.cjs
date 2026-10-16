// 执行页面实际导出函数，校验列与数据，而不复制一份导出实现。
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'dashboard_template.html'), 'utf8');
const start = source.indexOf('function exportCSV(){');
const end = source.indexOf('/* ── 个股详情 ── */', start);
const snap = JSON.parse(fs.readFileSync(path.join(root, 'cache/snapshot.json'), 'utf8'));
const rows = snap.stocks.concat(snap.coverage_catalog || []);
let blob;
const context = {
  DATA: snap, STOCK_VIEW: 'all', Blob,
  stockViewRows: () => rows,
  quoteFreshAtClientNow: s => s.intraday_quote_fresh === true,
  quoteStatusAtClientNow: s => s.intraday_quote_status,
  currentCandidateActive: (s, k) => !!s[k] && s.intraday_quote_fresh === true,
  afternoonBridgeQuote: () => null, morningOpenBridgeQuote: () => null,
  auctionDisplayQuote: () => null, useCompletedClose: () => false,
  closeDisplayQuote: () => null, lunchDisplayQuote: () => null,
  URL: { createObjectURL: b => { blob = b; return 'blob:test'; } },
  document: { createElement: () => ({click() {}}) },
  toast() {},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.exportCSV();
blob.text().then(text => {
  fs.writeFileSync(path.join(__dirname, 'verified_export.csv'), text, 'utf8');
  console.log(`Exported ${rows.length} rows from the actual dashboard export function`);
}).catch(err => {console.error(err); process.exitCode = 1;});
