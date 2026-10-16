"""在真实无头Chrome中核对默认入口、候选筛选与跨视图一致性。"""
import json
import re
import subprocess
from pathlib import Path
import tempfile

import config
import intraday

ROOT = Path(__file__).resolve().parent
CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
PROBE = r'''
<script>
window.onerror=function(msg,src,line){var e=document.getElementById('__err')||document.createElement('pre');e.id='__err';e.textContent=String(msg)+' @'+line;document.body.appendChild(e);};
setTimeout(async function(){
 var checks={};function check(k,v){checks[k]=!!v;}
 try{
  check('model_version_v3',DATA.intraday_model.version==='盘中观察初版3'
    &&DATA.intraday_model.rule_version==='盘中规则2026-09-28.3');
  check('close_confirmation_matches_active_rule',!DATA.intraday_close_confirmation
    ||DATA.intraday_close_confirmation.model_version===DATA.intraday_model.version
      &&DATA.intraday_close_confirmation.rule_version===DATA.intraday_model.rule_version);
  check('default_filter_is_clear',STATE.filters.states.length===0
    &&STATE.filters.industries.length===0&&STATE.filters.themes.length===0
    &&STATE.filters.boards.length===0&&activeFilterCount()===0);
  check('three_dimension_scores_are_complete',DATA.stocks.every(function(s){
    return s.intraday_score==null||s.intraday_score_available_components===3;}));
  check('current_strong_uses_all_qualification_gates',DATA.stocks.concat(DATA.coverage_catalog||[]).every(function(s){
    return s.current_strong_candidate!==true||Object.keys(s.current_strong_qualification||{}).length===10
      &&Object.keys(s.current_strong_qualification||{}).every(function(k){return s.current_strong_qualification[k]===true;});}));
  check('five_stock_views',document.querySelectorAll('#intraday-views button').length===5
    &&STOCK_VIEW==='strong');
  check('after_close_opens_factor_board',WORK_MODE==='close'
    &&document.getElementById('ov-work-close').classList.contains('on')
    &&document.getElementById('work-close-table').innerText.indexOf(DATA.close_strong_board.stocks[0].code)>=0);
  check('close_board_uses_existing_factor_membership_and_order',
    JSON.stringify(DATA.close_strong_board.stocks.map(function(s){return s.code;}))===
    JSON.stringify(DATA.stocks.filter(function(s){return s.persistent_strong===true;})
      .sort(function(a,b){return b.stock_strength_score-a.stock_strength_score||a.code.localeCompare(b.code);})
      .map(function(s){return s.code;})));
  var closeBlob=null,closeOldURL=URL.createObjectURL,closeOldClick=HTMLAnchorElement.prototype.click;
  URL.createObjectURL=function(blob){closeBlob=blob;return 'blob:close-smoke';};
  HTMLAnchorElement.prototype.click=function(){};exportCloseBoard();
  URL.createObjectURL=closeOldURL;HTMLAnchorElement.prototype.click=closeOldClick;
  var closeCSV=closeBlob?await closeBlob.text():'';
  check('close_export_matches_main_board',JSON.stringify(closeCSV.trim().split(/\r?\n/).slice(1)
    .map(function(line){var m=line.match(/^"([^"]*)"/);return m?m[1]:'';}))===
    JSON.stringify(DATA.close_strong_board.stocks.map(function(s){return s.code;})));
  document.querySelector('#work-switch button[data-work="live"]').click();
  check('manual_live_view_opens',WORK_MODE==='live'&&document.getElementById('ov-work-live').classList.contains('on'));
  document.querySelector('#work-switch button[data-work="close"]').click();
  check('manual_close_view_opens',WORK_MODE==='close'&&document.getElementById('ov-work-close').classList.contains('on'));
  DATA.coverage_catalog=DATA.coverage_catalog||[];
  DATA.intraday_model.max_quote_age_seconds=600;
  DATA.intraday_model.max_quote_future_seconds=90;
  var smokeNow=new Date();smokeNow.setHours(13,5,0,0);var simulatedSession='午盘';
  var pad=function(v){return String(v).padStart(2,'0');};
  var quoteStamp=smokeNow.getFullYear()+'-'+pad(smokeNow.getMonth()+1)+'-'+pad(smokeNow.getDate())
    +' '+pad(smokeNow.getHours())+':'+pad(smokeNow.getMinutes())+':00';
  Date.now=function(){return smokeNow.getTime();};
  sessionNow=function(){return simulatedSession;};
  var oldLatest=DATA.intraday_model.latest_valid_quote_at;
  DATA.intraday_model.latest_valid_quote_at=quoteStamp;
  check('valid_same_day_quote_opens_live_during_session',autoWorkMode()==='live');
  DATA.intraday_model.latest_valid_quote_at='2026-09-25 15:00:00';
  check('nontrading_or_stale_day_keeps_close_board',autoWorkMode()==='close');
  DATA.intraday_model.latest_valid_quote_at=oldLatest;
  DATA.coverage_catalog.push({code:'TEST001',name:'入口验收启动样本',coverage_only:true,traded:1,
    boards:['验收题材'],industry:['验收行业'],primary_industry:'验收行业',board_name:'沪主板',
    startup_candidate:true,current_strong_candidate:false,watch_candidate:false,trend_online:0,
    intraday_quote_fresh:true,intraday_quote_at:quoteStamp,intraday_score:86,intraday_score_available_components:3,
    intraday_trend_ok:true,intraday_observation_state:'初步转强，待收盘确认',change_pct:1,
    stock_strength_score:80,stock_strength_percentile:82,ret5:1,turnover:1,volume_ratio_closed:1,
    float_mcap:100,position60:50,live_dist_atr:0,fund_today_yi:null});
  DATA.coverage_catalog.push({code:'TEST002',name:'待评分异常验收样本',coverage_only:true,traded:0,
    boards:[],industry:[],primary_industry:'',board_name:'未知',startup_candidate:false,
    current_strong_candidate:false,watch_candidate:false,trend_online:null,
    intraday_quote_fresh:false,intraday_score:null,intraday_score_available_components:0,
    intraday_quote_status:'现价超出日内高低区间',change_pct:500,stock_strength_score:null,
    ret5:999,turnover:150,volume_ratio_closed:300,float_mcap:200000,position60:150,
    live_dist_atr:null,fund_today_yi:null});
  goPane('stocks');
  check('initial_entry_has_no_hidden_filter',STOCK_VIEW==='strong'&&activeFilterCount()===0
    &&STATE.filters.states.length===0);
  setStockView('startup');
  var startupRows=stockViewRows('startup',true);
  check('startup_visible_without_clearing',startupRows.some(function(s){return s.code==='TEST001';})
    &&document.getElementById('tb-stocks').innerText.indexOf('TEST001')>=0
    &&document.getElementById('stk-res').innerText.indexOf('另有')<0);
  check('fresh_intraday_candidate_uses_quote_time',currentCandidateActive(
    DATA.coverage_catalog[0],'startup_candidate')&&quoteFreshAtClientNow(DATA.coverage_catalog[0]));
  smokeNow=new Date(smokeNow.getTime()+3600000);simulatedSession='已收盘';
  check('expired_quote_leaves_current_entry_but_stays_in_all_samples',
    !currentCandidateActive(DATA.coverage_catalog[0],'startup_candidate')
    &&!stockViewRows('startup',true).some(function(s){return s.code==='TEST001';})
    &&stockViewRows('all',true).some(function(s){return s.code==='TEST001';}));
  smokeNow=new Date(smokeNow.getTime()-3600000);simulatedSession='午盘';
  STATE.filters.industries=['验收行业'];setStockView('startup');
  check('entry_switch_keeps_user_filters',STATE.filters.industries[0]==='验收行业'
    &&activeFilterCount()===1&&document.getElementById('stk-res').innerText.indexOf('另有 1 项筛选')>=0);
  onlyCurrentStockView();
  check('only_this_entry_clears_filters',STOCK_VIEW==='startup'&&activeFilterCount()===0
    &&stockViewRows('startup',true).some(function(s){return s.code==='TEST001';}));
  var startupExpected=stockViewRows('startup',true).map(function(s){return s.code;});
  var startupExportBlob=null,startupOldURL=URL.createObjectURL,startupOldClick=HTMLAnchorElement.prototype.click;
  URL.createObjectURL=function(blob){startupExportBlob=blob;return 'blob:startup-smoke';};
  HTMLAnchorElement.prototype.click=function(){};exportCSV();
  URL.createObjectURL=startupOldURL;HTMLAnchorElement.prototype.click=startupOldClick;
  var startupCSV=startupExportBlob?await startupExportBlob.text():'';
  var startupCodes=startupCSV.trim().split(/\r?\n/).slice(1).map(function(line){
    var m=line.match(/^"([^"]*)"/);return m?m[1]:'';});
  check('startup_export_uses_same_candidate_and_order',JSON.stringify(startupCodes)===JSON.stringify(startupExpected));
  renderOverview();
  var overviewRows=[].slice.call(document.querySelectorAll('#ov-stocks tbody tr'));
  check('overview_uses_same_startup_order',document.getElementById('ov-stock-title').innerText==='初步启动'
    &&overviewRows.length===Math.min(10,startupExpected.length)
    &&overviewRows.every(function(tr,i){return tr.innerText.indexOf(startupExpected[i])>=0;}));
  var outside=stockPoolRows().filter(function(s){return s.code==='TEST002';})[0];
  STATE.q='TEST002';renderStocks();
  check('search_outside_is_separate_and_not_counted',document.getElementById('search-outside').innerText.indexOf('TEST002')>=0
    &&document.getElementById('search-outside').innerText.indexOf('不计入')>=0
    &&document.getElementById('stk-res').innerText.indexOf('命中 0 只')>=0);
  STATE.q='';var allRows=stockViewRows('all',true);
  var anomalyIndex=allRows.findIndex(function(s){return s.code==='TEST002';});
  var lastScoredIndex=-1;allRows.forEach(function(s,i){
    if(s.stock_strength_score!=null||(s.intraday_score!=null&&!s.intraday_score_stale))lastScoredIndex=i;});
  check('all_samples_keeps_unscored_anomalies',anomalyIndex>=0
    &&allRows.length===stockPoolRows().length
    &&allRows[anomalyIndex].intraday_quote_status.indexOf('现价超出日内高低区间')>=0);
  check('all_samples_places_unscored_after_scored',anomalyIndex>lastScoredIndex);
  setStockView('all');renderOverview();
  var expected=stockViewRows('all',true).map(function(s){return s.code;});
  var exported=null,oldURL=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;
  URL.createObjectURL=function(blob){exported=blob;return 'blob:smoke';};
  HTMLAnchorElement.prototype.click=function(){};exportCSV();
  URL.createObjectURL=oldURL;HTMLAnchorElement.prototype.click=oldClick;
  var csv=exported?await exported.text():'';
  var csvLines=csv.trim().split(/\r?\n/);
  function csvWidth(line){var quoted=false,count=1;for(var i=0;i<line.length;i++){
    if(line[i]==='"'){if(quoted&&line[i+1]==='"'){i++;continue;}quoted=!quoted;}
    else if(line[i]===','&&!quoted)count++;}return count;}
  var csvCodes=csvLines.slice(1).map(function(line){var m=line.match(/^"([^"]*)"/);return m?m[1]:'';});
  check('export_uses_same_all_sample_order',JSON.stringify(csvCodes)===JSON.stringify(expected));
  check('export_columns_are_rectangular',csvLines.every(function(line){return csvWidth(line)===csvWidth(csvLines[0]);}));
  var sample=DATA.stocks[0];
  if(sample){showStock(sample.code);var detail=document.getElementById('dr-b').innerText;
    check('detail_shows_ma_and_quote_basis',detail.indexOf('日线MA10固定')>=0
      &&detail.indexOf('盘中MA10暂态')>=0&&detail.indexOf('历史价格口径')>=0);
    closeDrawer();}
  renderFresh();
  check('static_file_warning',document.getElementById('fresh-txt').innerText.indexOf('静态快照')>=0);
  check('no_page_error',!document.getElementById('__err'));
 }catch(e){checks.exception=String(e.stack||e);}
 document.title='SMOKE_JSON:'+JSON.stringify(checks);
},500);
</script>
'''


def run():
    template = (ROOT / 'dashboard_template.html').read_text(encoding='utf-8')
    snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
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
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
    html = template.replace('/*__DATA__*/null', payload)
    if '/*__DATA__*/null' in html:
        raise RuntimeError('dashboard data placeholder was not replaced')
    with tempfile.TemporaryDirectory(prefix='strength-smoke-') as tmp:
        page = Path(tmp) / 'smoke.html'
        page.write_text(html.replace('</body>', PROBE + '</body>'), encoding='utf-8')
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
