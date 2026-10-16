from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
text = (root / 'dashboard_template.html').read_text(encoding='utf-8')
start = text.index('function exportCSV(){')
end = text.index('\n}\n', start) + 2
original = text[start:end]
body = original[original.index('  var head='):original.index('  var blob=')]
# Keep the original formatter verbatim; its seven clock-dependent display calls
# read the context computed by the original browser functions at export time.
header = '''function buildStockCSV(res,DATA,contexts){
  function context(s){return contexts[s.code]||{};}
  function quoteFreshAtClientNow(s){return context(s).fresh;}
  function quoteStatusAtClientNow(s){return context(s).status;}
  function currentCandidateActive(s,key){return (context(s).candidates||{})[key];}
  function afternoonBridgeQuote(s){return context(s).bridge;}
  function morningOpenBridgeQuote(s){return context(s).openBridge;}
  function auctionDisplayQuote(s){return context(s).auction;}
  function closeDisplayQuote(s){return context(s).close;}
  function lunchDisplayQuote(s){return context(s).lunch;}
  function useCompletedClose(){return !!contexts.useCompletedClose;}
'''
tail = '''  return '\\ufeff'+lines.join('\\n');
}
if(typeof module!=='undefined'&&module.exports){
  module.exports=buildStockCSV;
  if(require.main===module){
    var input='';process.stdin.setEncoding('utf8');
    process.stdin.on('data',function(s){input+=s;});
    process.stdin.on('end',function(){var j=JSON.parse(input);process.stdout.write(buildStockCSV(j.rows,j.data,j.contexts));});
  }
}
'''
(root / 'csv_export.js').write_text(header+body+tail, encoding='utf-8')
# Preserve the stock order and all current-time qualification semantics.
replacement = '''function exportCSV(){
  var res=stockViewRows(STOCK_VIEW,true),contexts={useCompletedClose:useCompletedClose()};
  res.forEach(function(s){var candidates={};
    ['current_strong_candidate','current_pullback_candidate','startup_candidate','turn_weak_repair_candidate']
      .forEach(function(k){candidates[k]=currentCandidateActive(s,k);});
    contexts[s.code]={fresh:quoteFreshAtClientNow(s),status:quoteStatusAtClientNow(s),candidates:candidates,
      bridge:afternoonBridgeQuote(s),openBridge:morningOpenBridgeQuote(s),auction:auctionDisplayQuote(s),
      close:closeDisplayQuote(s),lunch:lunchDisplayQuote(s)};
  });
  function save(text){
    var blob=new Blob([text],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=''' + original.split('a.download=',1)[1].split(';a.click()',1)[0] + ''';
    a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},10000);toast(''' + original.split('toast(',1)[1].rsplit(');',1)[0] + ''');
  }
  if(!DATA.ui_lazy){save(buildStockCSV(res,DATA,contexts));return Promise.resolve();}
  if(!res.length){toast('No matching rows');return Promise.resolve();}
  var generation=DATA.ui_generation;
  toast('Exporting '+res.length+' rows...');
  return fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({version:generation,codes:res.map(function(s){return s.code;}),contexts:contexts})})
    .then(function(r){if(!r.ok)throw new Error(r.status===409?'数据版本已过期，请先更新页面':'导出失败 '+r.status);return r.text();})
    .then(save).catch(function(e){toast(e.message);throw e;});
}'''
text=text[:start]+replacement+text[end:]
text=text.replace('var DATA = /*__DATA__*/null;', '/*__CSV_SCRIPT__*/\n/*__UI_SCRIPT__*/\nvar DATA = /*__DATA__*/null;\nDATA=decodeDashboardPackage(DATA);')
text=text.replace('init();\n', 'installLazyDetails();\ninit();\n')
(root / 'dashboard_template.html').write_text(text, encoding='utf-8')
