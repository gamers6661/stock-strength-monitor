"""在真实无头Chrome中核对现行全部样本入口、报价时效、导出与后台版本一致性。"""
import json
import re
import subprocess
from pathlib import Path
import tempfile

import config
import intraday
import price_only

ROOT = Path(__file__).resolve().parent
CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
PROBE = r"""
<script>
window.onerror=function(msg){window.__smokeError=String(msg);};
setTimeout(async function(){
 var checks={};function check(k,v){checks[k]=!!v;}
 async function capture(fn){var result=null,oldURL=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;
  try{URL.createObjectURL=function(b){result=b;return 'blob:audit';};HTMLAnchorElement.prototype.click=function(){};fn();}
  finally{URL.createObjectURL=oldURL;HTMLAnchorElement.prototype.click=oldClick;}
  return result?await result.text():'';}
 function codes(csv){return csv.trim().split(/\r?\n/).slice(1).map(function(line){var m=line.match(/^"([^"]*)"/);return m?m[1]:'';});}
 function width(line){var q=false,n=1;for(var i=0;i<line.length;i++){if(line[i]==='"'){if(q&&line[i+1]==='"'){i++;continue;}q=!q;}else if(line[i]===','&&!q)n++;}return n;}
 try{
  check('active_model_and_rule',DATA.intraday_model.version===__ACTIVE_MODEL__&&DATA.intraday_model.rule_version===__ACTIVE_RULE__);
  check('fresh_scores_have_all_components',DATA.stocks.every(function(s){return s.intraday_score==null||s.intraday_score_stale||s.intraday_score_available_components===3;}));
  check('all_entry_has_no_hidden_filter',STOCK_VIEW==='all'&&activeFilterCount()===0);
  check('close_mode_button_and_content_agree',WORK_MODE==='close'&&document.getElementById('ov-work-close').classList.contains('on')
   &&document.querySelector('#work-switch button.on').dataset.work==='close');
  var members=DATA.close_strong_board.stocks.map(function(s){return s.code;});
  check('close_membership_and_order',JSON.stringify(members)===JSON.stringify(DATA.stocks.filter(function(s){return s.persistent_strong===true;})
   .sort(function(a,b){return b.stock_strength_score-a.stock_strength_score||a.code.localeCompare(b.code);}).map(function(s){return s.code;})));
  check('close_export_matches_board',JSON.stringify(codes(await capture(exportCloseBoard)))===JSON.stringify(members));
  document.querySelector('#work-switch button[data-work="live"]').click();
  check('manual_live_switch_consistent',WORK_MODE==='live'&&document.getElementById('ov-work-live').classList.contains('on')&&document.querySelector('#work-switch button.on').dataset.work==='live');
  document.querySelector('#work-switch button[data-work="close"]').click();
  check('manual_close_switch_consistent',WORK_MODE==='close'&&document.getElementById('ov-work-close').classList.contains('on')&&document.querySelector('#work-switch button.on').dataset.work==='close');
  var sample={code:'TEST001',name:'中文搜索验收',coverage_only:true,traded:1,boards:['验收题材'],industry:['验收行业'],primary_industry:'验收行业',board_name:'沪主板',stock_strength_score:null,
   startup_candidate:true,current_strong_candidate:false,intraday_quote_fresh:true,intraday_score:86,intraday_score_stale:false,intraday_score_available_components:3,change_pct:1};
  DATA.coverage_catalog.push(sample);
  goPane('stocks');STATE.q='中文搜索验收';renderStocks();
  check('chinese_search_returns_exact_sample',stockViewRows('all',true).length===1&&document.getElementById('tb-stocks').innerText.indexOf('TEST001')>=0);
  STATE.q='';STATE.filters.industries=['验收行业'];renderStocks();
  check('industry_filter_is_effective',stockViewRows('all',true).length===1&&stockViewRows('all',true)[0].code==='TEST001');
  clearStockFilters();
  check('clear_filters_restores_all_rows',activeFilterCount()===0&&stockViewRows('all',true).length===stockPoolRows().length);
  var now=new Date();now.setHours(13,5,0,0);var originalNow=Date.now,originalSession=sessionNow;
  var stamp=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0')+' 13:05:00';
  Date.now=function(){return now.getTime();};sessionNow=function(){return '午盘';};
  DATA.intraday_model.max_quote_age_seconds=600;DATA.intraday_model.max_quote_future_seconds=90;
  sample.intraday_quote_at=stamp;
  check('fresh_candidate_uses_source_time',currentCandidateActive(sample,'startup_candidate'));
  now=new Date(now.getTime()+3600000);
  check('expired_candidate_is_not_current_but_row_is_retained',!currentCandidateActive(sample,'startup_candidate')&&stockViewRows('all',true).some(function(s){return s.code==='TEST001';}));
  DATA.intraday_model.latest_valid_quote_at='2000-01-01 10:00:00';
  check('intraday_clock_stays_live_while_quotes_wait',autoWorkMode()==='live');
  Date.now=originalNow;sessionNow=originalSession;
  var expected=stockViewRows('all',true).map(function(s){return s.code;});var csv=await capture(exportCSV),lines=csv.trim().split(/\r?\n/);
  check('export_matches_filtered_rows_and_order',JSON.stringify(codes(csv))===JSON.stringify(expected));
  check('export_columns_are_rectangular',lines.length>1&&lines.every(function(line){return width(line)===width(lines[0]);}));
  check('export_has_no_fund_columns',!(/主力净额|资金流|超大单/.test(lines[0])));
  var production=DATA.stocks[0];showStock(production.code);
  document.querySelectorAll('#dr-b details').forEach(function(el){el.open=true;});
  var detail=document.getElementById('dr-b').innerText;
  check('detail_keeps_price_basis_and_affiliation',/历史价格口径/.test(detail)&&/归属与数据来源/.test(detail));
  check('detail_has_no_fund_reference',!(/历史资金|主力净额|超大单净额/.test(detail)));closeDrawer();
  DATA.runtime_contract=__CONTRACT__;
  renderUpdateState({snapshot_generated_at:DATA.generated_at});
  check('legacy_backend_is_visible_and_refresh_disabled',document.getElementById('update-state').textContent==='后台待重启'&&document.getElementById('btn-refresh').disabled);
  var good=Object.assign({snapshot_generated_at:DATA.scan_completed_at||DATA.generated_at,last_scan_ok:true,last_publish_ok:true},DATA.runtime_contract);
  renderUpdateState(good);
  check('matching_backend_is_synchronized',document.getElementById('update-state').textContent==='已同步'&&!document.getElementById('btn-refresh').disabled);
  good.snapshot_generated_at='2000-01-01 00:00:00';renderUpdateState(good);
  check('older_backend_snapshot_is_not_marked_synchronized',document.getElementById('update-state').textContent==='版本待核验');
  renderFresh();check('static_file_warning',document.getElementById('fresh-txt').innerText.indexOf('静态快照')>=0);
  check('no_page_error',!window.__smokeError);
 }catch(e){checks.exception=String(e.stack||e);}
 document.title='SMOKE_JSON:'+JSON.stringify(checks);
},500);
</script>
"""


def run():
    template = (ROOT / 'dashboard_template.html').read_text(encoding='utf-8')
    template = template.replace('/*__CSV_SCRIPT__*/', (ROOT / 'csv_export.js').read_text(encoding='utf-8'))
    template = template.replace('/*__UI_SCRIPT__*/', (ROOT / 'ui_client.js').read_text(encoding='utf-8'))
    snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    price_only.sanitize(snapshot)
    # Keep the real template and representative production rows, while trimming
    # large board/member arrays that do not participate in these UI assertions.
    snapshot['stocks'] = (snapshot.get('stocks') or [])[:2]
    snapshot['coverage_catalog'] = []
    snapshot['board_catalog'] = []
    snapshot['board_chain'] = []
    snapshot['daily_advice'] = []
    snapshot['close_strong_board'] = {
        'asof': snapshot['strength_model']['asof'],
        'factor_model_version': snapshot['factor_model_version'],
        'stocks': [{'code': s['code'], 'name': s['name'], 'score': s.get('stock_strength_score'),
                    'percentile': s.get('stock_strength_percentile'), 'ret5': s.get('ret5'),
                    'ret20': s.get('ret20'), 'trend_stage': s.get('trend_stage')}
                   for s in sorted((s for s in snapshot['stocks'] if s.get('persistent_strong') is True),
                                   key=lambda s: (-s.get('stock_strength_score', 0), s['code']))]
    }
    snapshot['close_strong_board']['count'] = len(snapshot['close_strong_board']['stocks'])
    snapshot['prior_close_monitor'] = {'rows': [], 'reason': '测试无昨日留档'}
    snapshot['intraday_new_strength'] = {'rows': []}
    payload = config.script_json(snapshot)
    html = template.replace('/*__DATA__*/null', payload)
    if '/*__DATA__*/null' in html:
        raise RuntimeError('dashboard data placeholder was not replaced')
    with tempfile.TemporaryDirectory(prefix='strength-smoke-') as tmp:
        page = Path(tmp) / 'smoke.html'
        probe=PROBE.replace('__ACTIVE_MODEL__',json.dumps(intraday.VERSION,ensure_ascii=False))
        probe=probe.replace('__ACTIVE_RULE__',json.dumps(config.INTRADAY_RULE_VERSION,ensure_ascii=False))
        import scoring, attack_model
        probe=probe.replace('__CONTRACT__',config.script_json(dict(code_close_refresh_version=scoring.CLOSE_REFRESH_VERSION,code_fund_reference_version=price_only.VERSION,code_attack_model_version=attack_model.LIVE_VERSION)))
        page.write_text(html.replace('</body>', probe + '</body>'), encoding='utf-8')
        result = subprocess.run([str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--user-data-dir=' + str(Path(tmp) / 'chrome'), '--virtual-time-budget=6000',
                                 '--dump-dom', page.as_uri()], capture_output=True, timeout=60)
        dom = result.stdout.decode('utf-8', 'replace')
        match = re.search(r'<title>SMOKE_JSON:(.*?)</title>', dom, re.S)
        if not match:
            print('FAIL: browser probe did not finish', result.stderr.decode('utf-8', 'replace')[-500:])
            return 1
        import html as html_module
        checks = json.loads(html_module.unescape(match.group(1)))
        for key, value in checks.items():
            print(key, ':', value)
        return 0 if checks and all(value is True for value in checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(run())
