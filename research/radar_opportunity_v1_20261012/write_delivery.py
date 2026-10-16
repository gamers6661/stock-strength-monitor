import hashlib,json,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro
OUT=Path(__file__).resolve().parent
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def link(name,label=None):return '['+(label or name)+']('+str(OUT/name).replace('\\','/')+')'
receipt=read('final_published_refresh.json');status=receipt['after'];pub=read('published_lists.json');frozen=read('final_frozen_compare.json');browser=read('browser_evidence.json');csv=read('page_detail_csv_consistency.json');examples=read('real_intraday_examples.json');changes=read('changed_files.json');forward=read('forward_report.json')
descriptions={'config.py':'新增独立RADAR_OPPORTUNITY与单位、用途；原评分配置保留。','radar_opportunity.py':'新增统一准入、全主板基准、三类机会、确认/维持/退出、冻结平台和事件、板块参考、收盘复核。无行情请求。','radar.py':'保留build_trend，新增独立build_opportunities委托。','scoring.py':'正常路径在盘中、板块、整理、结构、price_only和session_context后接入，留档及写盘前执行；竞价路径独立生成参考。','radar_ui.js':'新增三视图、类别/同行/风险筛选、任意股票原因查询、后端名单排序与统一CSV入口。','dashboard_template.html':'保留旧日线雷达，增加机会视图及详情，CSV入口支持显式空名单。','make_dashboard.py':'内联新雷达页面脚本及运行版本；离线只投影结果。','ui_payload.py':'雷达字段贯穿摘要、完整详情、索引CSV与压缩链路；空名单返回表头，仍校验版本。','csv_export.js':'原228列含义不变，追加11列版本、状态、收益与完整依据。','serve.py':'状态报告规则版本、运行代码哈希、快照哈希和数量；同版本事件恢复；发布回执关联generation。','check_dashboard.py':'增加新机会数据合同与磁盘/页面核验。','check_live_service.py':'核验实际代码/快照版本及哈希、筛选合同。','test_radar_opportunity.py':'49项独立业务边界和状态测试。','test_ui_payload.py':'验证新增列及版本，空导出仅表头。','test_attack_model.py':'旧竞价测试写盘目录隔离到临时目录，避免测试日志混入真实前向记录。','radar_forward_report.py':'只读SQLite和真实逐轮日志；新旧机制1/3/5日参考收益、按触发/确认及类别/半日/环境/同行分组，整体去重。'}
lines=['# 雷达机会 V1 实施与验收交付','',f"规则：`{ro.VERSION}`。依据为工作目录内《选股雷达完整优化方案 V1》。最终实际HTTP发布 `{status['last_scan']}`，数据版本 `{status['data_version']}`，generation `{status['ui_generation']}`。",'',
'## 1. 基线、恢复与保留范围','',
'源码、参数、快照、行情采集记录、SQLite备份及原名单在 '+link('before','before/')+'；文件摘要与实施前数据版本在 '+link('baseline_manifest.json')+'。基线数据版本 `1791783657739203500`，快照生成于13:40:22，源抓取13:39:02；原日线A197/B131/C117，原当前强势63、进攻候选76、初步启动51。完整原始名单保存在baseline_lists.json及实施前快照，未只保存汇总数。',
'', '保留原5/10/20日进攻评分、权重、A/B/C分档、主板股票池、同花顺分类、板块机会及指数规则、成员周更、300秒刷新。资金流继续停用。新增模块只读已有报价及历史，不增加行情请求。',
'', '恢复脚本 '+link('恢复基线.ps1')+' 默认仅预览；执行加`-Execute`，同时回退正式日线数据库加`-RestoreHistory`。脚本只在服务扫描和发布空闲时停止指定项目进程，保存当前新增文件/快照/事件及数据库边车，恢复before版本并重建旧页面。未实际执行破坏当前部署的回退。',
'', '## 2. 修改文件与逐文件差异','', '| 文件 | 操作 | 具体变化 |', '|---|---|---|']
for c in changes:lines.append('| '+c['file']+' | '+c['action']+' | '+descriptions.get(c['file'],'见逐文件差异')+' |')
lines += ['', '逐文件完整diff：'+link('diffs','diffs/')+'；旧/新哈希：'+link('changed_files.json')+'。', '', '## 3. 参数、口径与状态','',
'全部机会阈值集中在`config.RADAR_OPPORTUNITY`：', '', '| 类别 | R0 | E0 | 位置与背景 |', '|---|---|---|',
'| 强势再启动 | ≥2% | ≥1个百分点 | 合格整理背景；P>冻结Hc+缓冲；守开盘、MA5*、MA10* |',
'| 突破启动 | ≥3% | ≥2个百分点 | 25根核心历史，P>首次预警前H5+缓冲；守开盘、MA10*、MA20*；不排除昨日A |',
'| 持续进攻 | ≥2% | ≥1个百分点 | 事前完成日A；守开盘、MA5*、MA10* |',
'| 突破预警 | ≥2% | ≥1个百分点 | 同突破与位置条件，仅预警 |', '',
'缓冲=max(0.01元,0.1×已核验当前尺度ATR20)。H5取首次预警前5个完成日最高价最大值，不含当日；Hc复用原强势整理模块的真实平台。MA*、ATR及价格尺度复用现有核验；未知保持null，正式门槛使用未舍入值。合并stocks与coverage_catalog按代码去重；M0使用全主板有效报价等权均值，缺失仍在分母，覆盖≥80%才正式支持E0。', '',
'首次正式条件满足即待确认；同半日两次不同源报价、跨度≥300秒、相邻≤600秒后正式入池。重复、倒退、生成时间变化不增计数；竞价和14:57后不新增确认；午休冻结，午后重确认。维持需R0>0、E0>0、守开盘与必要MA，无严重转弱，突破类P>冻结平台；低于正式门槛但维持成立为进攻减速。平台/均线失守或严重转弱退出；数据缺失为判断暂停，恢复需重确认。', '',
'事件保存真实平台/整理起点、ATR、背景日期、规则/尺度身份、首次观察/触发/确认及价格。突破/再启动分类窗口为首次正式触发当天加随后两个交易日；同事件恢复不延长。旧事件结束后至少两个完成收盘回旧平台，且新H锚点更晚，才允许新突破；再启动需新的合格整理。版本/尺度观察不能伪装为经济新启动。', '',
'市场提示：M0≥0.5%且上涨≥55%为偏强；M0≤-1%且上涨≤35%为偏弱；其余有效为分化；口径不足为未知。改变须同半日两次有效源采样。同行参考剔除本股，至少5只、覆盖≥80%、上涨≥50%、中位数>M0；不救个股资格、不累加概念奖励。严重风险沿用原规则；位置偏热严格超过3.5ATR，触板未封及成交限制独立展示。', '',
'主标签优先级为再启动→突破→持续，只用于去重标签。默认列表固定按E0→原live_attack_score→R0降序→代码升序；缺分置后，不补0。当前、受限、待确认、预警、跟踪分区。收盘正式日线到库后，用同批有效主板收市M0、冻结平台与正式日线复核；这不会追加盘中确认，也不会改写原盘中风险/记录。', '',
'## 4. 同一冻结输入对照','',
'输入 '+link('frozen_inputs.json.gz')+'；SHA256 `'+frozen['input_sha256']+'`。包含原快照、该批真实报价、原股票池、历史K线、交易日历及核验上下文。', '',
'最终重放 '+link('final_frozen_compare.json')+'：删除新增雷达字段后，整个原快照逐字段相同，包括个股分数/档位、成员及板块趋势；新增计算耗时 '+str(round(frozen['added_compute_seconds'],3))+'秒。原CSV228列与新CSV前228列逐单元格相同（'+link('frozen_compare.json')+'）。早期性能记录232.951秒仍保留；最终去掉重复时间解析后，同冻结输入降至约24秒，未删样本。', '',
'冻结输入只有一批源报价，因此正式当前机会0、待确认81、预警34，符合两次采样要求。全部代码的原档位/旧候选、新标签/状态及逐类未通过/未知原因：'+link('frozen_all_reasons.csv')+'。最终冻结结果 '+link('final_frozen_result.json.gz')+'。', '',
'## 5. 业务边界与测试','',
'原始源码隔离基线488项全部通过：'+link('baseline_original_source_complete_tests.txt')+'。最终完整回归538项全部通过：'+link('full_tests.txt')+'。新雷达49项加摘要/CSV与类别筛选7项共56项通过：'+link('special_and_csv_tests.txt')+'。页面检查 '+link('dashboard_check.txt')+'、服务检查 '+link('live_check.txt')+' 均通过。', '',
'已覆盖：下跌A不入池，非A及昨日A突破允许，非A合格整理允许再启动，普通修复不能冒充；板块不替代资格；重复/倒退报价、午休/跨半日、跨日、版本重置；平台及ATR不漂移、尺度变化、三交易日过期、新事件重建；数据未知/价格口径未知不记0；覆盖79.99%与80%；守平台/MA退出与减速；多类同股去重和排序；已知受限、竞价及14:57后不确认；正式收盘独立复核；同版本恢复和离线投影；空导出仅表头。具体测试可按test_radar_opportunity.py方法名逐项定位。', '',
'失败记录单独保留：首次基线测试遇真实服务写锁（非业务公式失败）；隔离旧源码首跑缺原测试fixtures，补齐未改动fixtures后488项通过。完整测试中的“publish failed”等日志是故障注入预期，最终unittest结果OK。真实浏览器初次空池导出400已修正并重验；旧竞价测试日志污染已隔离，测试记录移入研究目录，真实事件state未被改写。最终无未解决测试失败。', '',
'离线重新生成页面前后，快照、事件state、真实逐轮及发布日志哈希一致：'+link('offline_projection_check.json')+'。', '',
'## 6. 实际发布、名单与页面证据','',
f"按现有方式重启，实际运行代码哈希与快照哈希均为`{status['code_radar_opportunity_hash']}`。最终POST /__refresh：`{receipt['before']['data_version']}`→`{status['data_version']}`；扫描/发布成功，generation `{status['ui_generation']}`。刷新回执与原样磁盘快照："+link('final_published_refresh.json')+'、'+link('final_published_refresh_snapshot.json.gz')+'。', '',
'最终耗时 '+str(status['last_pipeline_performance']['seconds'])+'秒（扫描'+str(status['last_pipeline_performance']['scan_seconds'])+'秒，发布'+str(status['last_pipeline_performance']['publish_seconds'])+'秒），不修改300秒采集频率。首次当天正式日线同步的早期冷扫描曾330秒，单独留在日志中；最终常规刷新已在300秒内，不将冷启动与常规缓存刷新混算。', '',
'最终当前名单/分类数量：`'+json.dumps(pub['counts'],ensure_ascii=False)+'`。收盘复核按事件分类计数（同股可能多类，不冒充独立股票数）：`'+json.dumps((pub.get('close_review') or {}).get('counts'),ensure_ascii=False)+'`。收盘后的空当前池和历史盘中确认是不同时间口径，页面分别显示；不补名额。完整原/新名单、基准及收盘逐事件结果：'+link('published_lists.json')+'。全池逐股未入选原因及冻结事件：'+link('published_all_reasons.csv')+'。', '',
'盘中真实代表来源为'+examples['generated_at']+'发布，版本'+str(examples['receipt'])+'，当前'+str(examples['counts']['current'])+'只、受限'+str(examples['counts']['limited'])+'只；并非用收盘数据回填。'+link('real_intraday_examples.json')+'含完整依据。', '', '| 场景 | 实际代表 |', '|---|---|']
for label,row in examples['examples'].items():lines.append('| '+label+' | '+(row['code']+' '+row['name'] if row else '该次实际样本无此场景；不制造案例')+' |')
lines += ['', '真实HTTP截图与下载在 `output/playwright/radar-v1/`：current-http、category-restart/breakout/sustained、follow-http、daily-http、detail-http、nonselected-detail-http、empty-http、close-detail-http。截图来自127.0.0.1:8848，未用离线file页面替代。', '',
'浏览器 '+link('browser_evidence.json')+' 核对三个类别、三视图、任意未入选查询与空池；页面异常0。浏览器下载的current/follow/empty CSV与后端同代码、同顺序、239列、每条完整机会对象与磁盘相同：'+link('page_detail_csv_consistency.json')+'。日线背景CSV另存daily-A.csv，保留原定义。压缩摘要/完整详情由check_live_service核验。', '',
'## 7. V1冻结、前向对照与数据缺口','',
'冻结记录：`cache/radar_opportunity_v1/rules_frozen.json`；同版本参数变化会拒绝新计算，调整需新版本与新观察期。状态atomic_write复用扫描写锁；事件逐轮日志保存当时池、成员、M0/报价和原A/attack_watch/startup名单，发布回执保存generation及data_version。'+link('forward_report.json')+'为真实记录的前向研究起点，按正式触发与确认分别、类别/半日/环境/同行分组，整体按代码+时刻+阶段去重，不回填历史池。', '',
'仍未解决且未替换的缺口：', '',
'- 缺完整盘口、同时间量能序列及真实成交记录：只作价格机会/采样确认，不能声称放量、抢筹或可成交。',
'- 缺完整可靠公告/政策/减持等事件源：消息风险未核验，不生成“无消息风险”。',
'- 少量历史/价格尺度/报价不完整对象保持判断暂停或待核验；逐股数量与原因见published_all_reasons.csv，缺失仍进主板覆盖分母。最终行情增量状态：`'+json.dumps(status['last_pipeline_performance'].get('kline_acquisition'),ensure_ascii=False)+'`。',
'- 本日尚无随后1/3/5个完成交易日，不提供收益效果结论；20日数据验证、60日及分组样本充足检查需后续真实采样积累。研究工具可后续只读重跑，不自动寻优阈值。',
'- 开发期最早真实记录部分未保存完整前向基准或报价昨收日期未对齐：当前missing_baselines='+str(forward['missing_baselines'])+'，保留缺口，不用后来的行情反写首次信号。正式冻结后完整逐轮基准留档；第一轮已确认事实及首次时间仍保留。',
'- 五分钟采样不能覆盖完整日内路径，最大不利幅度只使用信号后采样及随后完成日OHLC，不拿信号前的当日最低价；参考收益不等于交易收益。', '',
'本次工程验收证明规则、状态与数据链路按规格运行；投资效果尚待前向观察。']
(OUT/'验收交付.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
previous=json.loads((ro.directory()/'rules_frozen.json').read_text(encoding='utf-8')) if (ro.directory()/'rules_frozen.json').exists() else {}
record=dict(version=ro.VERSION,parameters=json.loads(json.dumps(config.RADAR_OPPORTUNITY)),implementation_hash=ro.IMPLEMENTATION_HASH,accepted_data_version=status['data_version'],generation=status['ui_generation'],frozen_at=previous.get('frozen_at') or status['time'],source_manifest=changes,forward_start_publication=previous.get('forward_start_publication') or status['last_scan'])
with config.pipeline_guard():config.atomic_write_text(ro.directory()/'rules_frozen.json',json.dumps(record,ensure_ascii=False,indent=2))
(OUT/'V1冻结记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('已生成验收交付并冻结V1',status['data_version'])
