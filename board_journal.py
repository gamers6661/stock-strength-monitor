"""Read-only board journal projection; shared scores and membership are never changed."""
import gzip
import hashlib
import html
import json
import os
import re
import urllib.request
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

VERSION = 'board-journal-20261022.1'
TZ = timezone(timedelta(hours=8))
ROOT = config.CACHE_DIR / 'board_journal'
NEWS_URL = 'https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page={page}&page_size=100&dire=f&dpc=1&pagesize=100'
MAX_DAYS = 10
_NEWS_WORKER = None
_NEWS_WORKER_LOCK = threading.Lock()
_NEWS_REFRESH_LOCK = threading.Lock()


def clock():
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def read(path, default=None):
    try:
        raw = path.read_bytes()
        return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)
    except (OSError, ValueError, EOFError):
        return default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if path.suffix == '.gz':
        data = gzip.compress(data, compresslevel=3)
    tmp = path.with_name(path.name + '.%s.%s.tmp' % (os.getpid(), threading.get_ident()))
    tmp.write_bytes(data)
    tmp.replace(path)


def plain(value):
    text = re.sub(r'<[^>]+>', '', html.unescape(str(value or '')))
    text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), text)
    return re.sub(r'\s+', ' ', text).strip()


def safe_url(value):
    value = str(value or '').replace('\\/', '/')
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if parsed.scheme == 'https' and parsed.hostname in ('finance.sina.cn', 'finance.sina.com.cn') and not parsed.username:
        return value
    return None


def fetch_page(page):
    request = urllib.request.Request(NEWS_URL.format(page=page), headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/7x24/'})
    with urllib.request.urlopen(request, timeout=7) as response:
        result = json.load(response).get('result') or {}
    if result.get('status', {}).get('code') != 0:
        raise ValueError('新浪快讯状态异常')
    feed = (result.get('data', {}).get('feed') or {}).get('list')
    if not isinstance(feed, list) or not feed:
        raise ValueError('新浪快讯列表为空')
    out = []
    now = clock()
    for item in feed:
        body = plain(item.get('rich_text'))
        at = str(item.get('create_time') or '')
        try:
            published = datetime.fromisoformat(at)
        except ValueError:
            continue
        if not body or published > now + timedelta(minutes=2):
            continue
        url = safe_url(item.get('docurl'))
        if not url:
            try:
                ext = json.loads(item.get('ext') or '{}')
                url = safe_url(ext.get('docurl'))
            except (ValueError, TypeError):
                pass
        if not url:
            continue
        match = re.match(r'【([^】]+)】', body)
        title = match[1] if match else re.split(r'[。！？]', body, 1)[0][:90]
        digest = hashlib.sha256(re.sub(r'\W+', '', body).encode()).hexdigest()[:20]
        out.append(dict(id=digest, title=title, excerpt=body[:200], text=body,
                        source='新浪财经快讯', url=url, published_at=at,
                        first_seen_at=str(now), category='媒体快讯'))
    return out


def _refresh_news():
    now = clock()
    path = ROOT / 'news.json.gz'
    old = read(path, {}) or {}
    try:
        age = (now - datetime.fromisoformat(old.get('checked_at', ''))).total_seconds()
        if 0 <= age < 300:
            return old
    except ValueError:
        pass
    errors, received = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fetch_page, page) for page in (1, 2, 3)]
        for page, job in enumerate(jobs, 1):
            try:
                received.extend(job.result())
            except Exception as exc:
                errors.append('第%d页：%s' % (page, str(exc)[:100]))
    events = {e['id']: e for e in old.get('events', [])}
    for event in received:
        if event['id'] in events:
            event['first_seen_at'] = events[event['id']]['first_seen_at']
        events[event['id']] = event
    cutoff = str(now - timedelta(days=7))
    events = sorted((e for e in events.values() if e['published_at'] >= cutoff),
                    key=lambda e: (e['published_at'], e['id']), reverse=True)[:3000]
    out = dict(checked_at=str(now), last_success_at=str(now) if received else old.get('last_success_at'),
               latest_published_at=max((e['published_at'] for e in events), default=None),
               status='ok' if not errors else 'partial' if received else 'failed',
               errors=errors, batch_count=len({e['id'] for e in received}), events=events,
               scope='新浪财经最近三页快讯；持续增量留存，不代表全市场新闻全覆盖')
    write(path, out)
    return out


def refresh_news():
    # Publishing and the independent worker share the same cache in this process.
    with _NEWS_REFRESH_LOCK:
        return _refresh_news()


def numeric(value):
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stock(row, day=None, auction=False):
    relay = row.get('emotion_relay') or {}
    strength = row.get('market_strength') or {}
    valid = bool(relay.get('valid')) and not relay.get('suspended_current') and not auction
    if day and str(relay.get('quote_at') or '')[:10] != day:
        valid = False
    change = relay.get('feedback_pct') if valid else (strength.get('emotion_parts') or {}).get('R0')
    quote_at = relay.get('quote_at') if valid else strength.get('emotion_at')
    if day and str(quote_at or '')[:10] != day:
        change = None
    if auction:
        context = row.get('session_context') or {}
        current = context.get('quote_valid') and str(context.get('quote_at') or '')[:10] == day
        change = context.get('gap_pct') if current else None
        quote_at = context.get('quote_at') if current else None
    return dict(code=str(row['code']), name=row.get('name') or row['code'],
                change_pct=change if numeric(change) else None,
                amount_wan=relay.get('amount_wan') if valid else row.get('amount_wan'),
                quote_at=quote_at,
                trend_score=strength.get('trend_score'), emotion_score=strength.get('emotion_score'),
                trend_strong=bool(strength.get('trend_strong')), emotion_strong=bool(strength.get('emotion_strong')),
                ret5=row.get('ret5'), float_mcap=row.get('float_mcap'),
                valid=valid, sealed=bool(valid and relay.get('sealed')),
                touched=bool(valid and relay.get('touched')),
                height=relay.get('height') if valid and relay.get('height_exact') else None,
                prior_height=relay.get('prior_height') if relay.get('prior_exact') else None,
                prior_sealed=relay.get('prior_sealed'),
                suspended=bool(relay.get('suspended_current')),
                basis=row.get('theme_basis') or '同花顺成员归属',
                roles=relay.get('roles') or [], risks=relay.get('risks') or [])


# Explicit topic vocabulary; these links describe the affected segment, not listed-company beneficiaries.
TOPIC_TERMS = {
    'PCB概念': ('PCB', '印制电路板', '封装基板', 'FC-BGA', 'IC载板'),
    '芯片概念': ('AI芯片', '芯片', '半导体'),
    '先进封装': ('先进封装', 'CoWoS', '2.5D封装', '3D封装'),
    '电机': ('电动机', '伺服电机', '驱动电机', '电机行业', '电机板块'),
    '电机Ⅱ': ('电动机', '伺服电机', '驱动电机', '电机行业', '电机板块'),
    '国有大型银行Ⅱ': ('国有大行', '六大行', '大型商业银行', '银行业'),
    '地面兵装Ⅱ': ('地面兵装', '地面装备', '装甲装备'),
    '兵装重组概念': ('兵器装备集团', '兵装重组'),
}
CATALYST_RULES = [
    ('risk', '事件扰动', r'终止|取消|推迟|延期|下调|禁令|制裁|停产|撤回',
     '事件改变了原有落地节奏或供需预期，影响取决于涉及范围与后续处置。',
     '关注后续公告是否明确影响范围、恢复安排和实际损失。'),
    ('capacity', '投资扩产', r'投资(?!者|人|机会|建议|风险|策略|评级|价值|收益|回报|经理|组合|银行)|出资|扩产|扩建|共建|建厂|新建.{0,10}(?:产线|工厂)|产能建设',
     '新增资本投入和产线建设会影响相关环节的产能与供货预期；建设、试产和量产分别对应不同兑现阶段。',
     '后续重点跟踪资金到位、产线建设、设备安装与量产时间，区分规划产能和实际交付。'),
    ('order', '订单合作', r'获得.{0,12}订单|订单.{0,12}(?:金额|亿元|万元|增长|落地)|签约|签署|供货协议|供应协议|合同|中标|达成.{0,8}合作|交付',
     '订单和合作首先影响客户需求、供货关系与交付预期，收入体现还取决于执行节奏。',
     '关注合同规模、交付期限、执行进度及后续披露的收入贡献。'),
    ('policy', '政策会议', r'政策|规划|指导意见|行动方案|补贴|降准|降息|会议|监管',
     '政策与会议可能改变行业需求、成本或准入条件，传导取决于适用范围与实施细则。',
     '关注正式文件、实施时间、适用对象和配套细则。'),
    ('restructure', '重组整合', r'重组|并购|收购|资产注入|整合|股权转让',
     '重组整合会改变资产边界和资源配置预期，后续审批与交易方案决定推进节奏。',
     '关注交易方案、审批进度、资产范围与完成条件。'),
    ('product', '产品技术', r'发布.{0,12}(?:产品|新品|技术|模型|设备)|(?:产品|新品|技术|模型).{0,8}发布|推出|新品|研发|技术突破|量产|投产|试产|获批|批准',
     '产品与技术进展带来供给升级预期，能否转化为业务增量要看验证、客户导入与规模交付。',
     '关注产品验证、客户导入、量产节奏与实际订单。'),
    ('performance', '业绩供需', r'业绩|营收|净利润|预增|预减|涨价|提价|降价|缺货|供不应求',
     '业绩或供需变化会影响盈利预期，应结合变化幅度、持续时间和企业实际敞口观察。',
     '关注后续财报、价格持续性、库存与订单变化。'),
    ('expectation', '产业预期', r'有望|预计|预测|将成为|需求.{0,8}(?:增长|提升)|市场空间',
     '产业展望提供中长期预期线索，落地节奏仍由产品、产能和订单进展决定。',
     '关注后续是否出现可量化的产品、订单或产能进展。'),
]


def catalyst_for(event, relation):
    if relation == 'member':
        return None
    body = plain(event.get('text') or event.get('excerpt') or '')
    body = re.sub(r'^【[^】]+】', '', body).strip()
    title = event.get('title') or ''
    # Negative words in an unrelated trailing paragraph must not override a positive headline.
    head = title + '。' + re.split(r'[。！？]', body, 1)[0]
    def event_text(value):
        # Theme names describe a classification, not a newly occurring event.
        return re.sub(r'[^，。；：、\s]{0,16}(?:概念|板块)', '', value)
    rules = CATALYST_RULES
    # A regulator's policy measures are not a commercial contract, even if they mention cooperation.
    if re.search(r'监管局|监管总局|国务院|人民银行|工信部|发改委', title) and re.search(r'通知|措施|意见|政策|规划|探索|鼓励|推进', title + body):
        rules = sorted(rules, key=lambda rule: 0 if rule[0] == 'policy' else 1)
    for kind, label, pattern, transmission, watch in rules:
        target = head if kind == 'risk' else title + '。' + body
        if not re.search(pattern, event_text(target), re.I):
            continue
        sentences = [v.strip() for v in re.split(r'(?<=[。！？])', body) if v.strip()]
        points = [v for v in sentences if re.search(pattern, v, re.I)][:2]
        if not points:
            points = sentences[:1]
        milestones = [v for v in sentences if re.search(r'(?:20\d{2}年|明年|年末|年底|上半年|下半年).*(?:建设|完工|设备|试产|量产|供货|交付)|(?:计划|预计|有望).*(?:量产|投产|交付|完工)', v)]
        timing = milestones[0][:240] if milestones else ''
        # Retain factual excerpts rather than adding unsourced supplier or earnings claims.
        return dict(kind=kind, label=label, points=[v[:260] for v in points],
                    transmission=transmission, watch=watch, timing=timing,
                    phase='规划／推进' if re.search(r'将|拟|计划|预计|有望', head + timing) else '报道进展',
                    attribution='据' + event.get('source', '报道'))
    return None


def news_for(name, members, stocks, events, asof):
    terms = {name}
    short = re.sub(r'(概念|板块|Ⅱ)$', '', name)
    if len(short) >= 2:
        terms.add(short)
    names = {stocks[c]['name']: c for c in members if c in stocks and len(stocks[c]['name']) >= 3}
    matches = []
    for event in events:
        if event['published_at'] > asof or event['first_seen_at'] > asof:
            continue
        text = event.get('text', event['excerpt'])
        title = event['title']
        # Samsung Electro-Mechanics is a company name in substrate news, not the motor industry.
        match_text = text.replace('三星电机', '') if short == '电机' else text
        match_title = title.replace('三星电机', '') if short == '电机' else title
        found = sorted(t for t in terms if len(t) >= 2 and t.lower() in match_text.lower())
        related = [t for t in TOPIC_TERMS.get(name, ()) if t.lower() in match_text.lower()]
        companies = [n for n in names if n in text]
        if not found and not related and not companies:
            continue
        out = {k: event[k] for k in ('id', 'title', 'excerpt', 'source', 'url', 'published_at', 'first_seen_at', 'category')}
        out['stock_codes'] = [names[n] for n in companies]
        kind = 'theme_title' if any(t.lower() in match_title.lower() for t in found) else 'theme_text' if found else 'industry_chain' if related else 'member'
        out['match_kind'] = kind
        out['match'] = ('题材名称：' + '、'.join(found) if found else
                        '产业环节：' + '、'.join(related) if related else '成员公司：' + '、'.join(companies[:3]))
        scoped_event = event
        if re.search(r'要闻|汇总|盘点|早报|午报|晚报|新闻联播', title):
            # Digest paragraphs can concern unrelated actors. Classify only the matched sentences.
            fragments = re.split(r'[。！？；\n]+', match_text)
            local_terms = found + related + companies
            relevant = [part.strip() for part in fragments if any(t.lower() in part.lower() for t in local_terms)]
            scoped = '。'.join(relevant)
            scoped_event = dict(event, title='', text=scoped, excerpt=scoped[:260])
            out['excerpt'] = scoped[:260]
            out['original_title'] = title
            out['title'] = (relevant[0][:100] if relevant else title) + '（综述摘录）'
        out['catalyst'] = catalyst_for(scoped_event, kind)
        documents = re.findall(r'《([^》]{5,100})》', scoped_event.get('text') or text)
        publisher = re.split(r'[：:]', title, 1)[0] if re.search(r'[：:]', title) else ''
        if documents and out['catalyst'] and out['catalyst']['kind'] == 'policy':
            out['event_key'] = '|'.join([event['published_at'][:10], event['source'], publisher, documents[0]])
            out['event_document'] = documents[0]
        matches.append(out)
    matches.sort(key=lambda e: e['published_at'], reverse=True)
    # Genuine events precede market recaps so a six-item cap cannot crowd catalysts out.
    matches.sort(key=lambda e: (0 if e.get('catalyst') else 1,
                               {'theme_title': 0, 'theme_text': 1, 'industry_chain': 2, 'member': 3}[e['match_kind']]))
    grouped, positions = [], {}
    for event in matches:
        key = event.get('event_key') or event['url']
        if key not in positions:
            positions[key] = len(grouped)
            grouped.append(event)
            continue
        primary = grouped[positions[key]]
        reports = primary.setdefault('related_reports', [])
        if not any(r['url'] == event['url'] for r in reports) and event['url'] != primary['url']:
            reports.append({k: event[k] for k in ('title', 'url', 'published_at', 'excerpt')})
    return grouped[:8]


def start_news_worker():
    global _NEWS_WORKER
    with _NEWS_WORKER_LOCK:
        if _NEWS_WORKER is not None and _NEWS_WORKER.is_alive():
            return
        def work():
            while True:
                threading.Event().wait(300)
                try:
                    refresh_news()
                    refresh_definitions()
                except Exception:
                    # Last successful cache remains available; next cycle retries.
                    pass
        _NEWS_WORKER = threading.Thread(target=work, name='board-journal-news', daemon=True)
        _NEWS_WORKER.start()


def live_news(base):
    now = str(clock())
    if base.get('date') != now[:10]:
        raise ValueError('Historical journals do not read current news')
    news = read(ROOT / 'news.json.gz', {}) or {}
    events = news.get('events') or []
    definitions = read(ROOT / 'definitions.json.gz', {}) or {}
    by_board = {identity: news_for(b['name'], b['members'], base['stocks'], events, now)
                for identity, b in base['boards'].items()}
    return dict(date=base['date'], source_at=base['source_at'],
                news={k: news.get(k) for k in ('checked_at', 'last_success_at', 'latest_published_at', 'status', 'errors', 'batch_count', 'scope')},
                by_board=by_board,
                definitions={identity: definition_for(b, definitions) for identity, b in base['boards'].items()})


# These are broad cross-industry labels, not a size-based deletion of real sectors.
BROAD_THEMES = {'比亚迪概念', '一带一路'}
INDUSTRY_GLOSSARY = {
    '电机': '围绕电能与机械能相互转换的设备及相关产品形成的行业，包括电动机、发电机等。',
    '电机Ⅱ': '围绕电能与机械能相互转换的设备及相关产品形成的行业，包括电动机、发电机等。',
    '国有大型银行Ⅱ': '以国有大型商业银行为主体的银行细分行业，主要涉及存贷款、结算和综合金融服务。',
    '地面兵装Ⅱ': '围绕地面作战装备及配套产品形成的军工细分行业。',
}
_DEFINITION_LOCK = threading.Lock()


def refresh_definitions(priority=()):
    """Bounded, cached source descriptions; never block every board on an external request."""
    with _DEFINITION_LOCK:
        path = ROOT / 'definitions.json.gz'
        saved = read(path, {}) or {}
        catalog = read(config.CACHE_DIR / 'ths_concepts.json', {}) or {}
        codes = {name: code for code, name in (catalog.get('detail') or {}).items()}
        now = clock()
        names = list(dict.fromkeys(list(priority) + list(codes)))
        due = []
        for name in names:
            if name not in codes:
                continue
            old = saved.get(name, {})
            try:
                fresh = (now - datetime.fromisoformat(old['checked_at'])).total_seconds() < (604800 if old.get('text') else 3600)
            except (KeyError, ValueError):
                fresh = False
            if not fresh:
                due.append(name)
            if len(due) >= 8:
                break
        def fetch(name):
            url = 'https://q.10jqka.com.cn/gn/detail/code/' + str(codes[name]) + '/'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=6) as response:
                    body = response.read(1000000).decode('gbk', errors='replace')
                # Validate the topic title before using a definition from this page.
                title = re.search(r'<h3[^>]*>\s*(.*?)<span', body, re.S)
                match = re.search(r'<h4[^>]*>\s*定义\s*</h4>\s*<p[^>]*>(.*?)</p>', body, re.S)
                if not title or plain(title[1]) != name or not match or not plain(match[1]):
                    raise ValueError('页面未返回对应题材定义')
                return name, dict(text=plain(match[1])[:1600], source='同花顺题材定义',
                                  url=url, checked_at=str(now), status='ok')
            except Exception as exc:
                old = dict(saved.get(name) or {})
                old.update(checked_at=str(now), status='cached' if old.get('text') else 'missing',
                           error=str(exc)[:100])
                return name, old
        if due:
            with ThreadPoolExecutor(max_workers=4) as pool:
                saved.update(dict(pool.map(fetch, due)))
            write(path, saved)
        return saved


def definition_for(board, definitions):
    if board['type'] == 'industry':
        text = INDUSTRY_GLOSSARY.get(board['name'])
        return dict(text=text or ('按同花顺行业分类归集的“' + board['name'] + '”方向；成员归属以该分类为准。'),
                    source='行业术语释义' if text else '同花顺分类口径', url=None,
                    status='glossary' if text else 'scope')
    return definitions.get(board['name']) or dict(text=None, source=None, status='missing')


def strong_evidence(board, day, reliable, auction, daily_asof=None):
    """Board-page eligibility follows the existing chronological index trend."""
    current = board.get('index_current') or {}
    daily = board.get('index_trend') or {}
    target = str(daily_asof or daily.get('expected_asof') or '')[:10]
    live = bool(current.get('ready') and current.get('asof') == day
                and current.get('mode') in ('current', 'close'))
    completed = bool(daily.get('ready') and target and daily.get('asof') == target
                     and target <= day)
    index = current if live else daily if completed else {}
    broad = board['type'] == 'theme' and board['name'] in BROAD_THEMES
    online = bool(index.get('trend_online'))
    startup = bool(index.get('startup'))
    holding = bool(index.get('priority_observation') and (online or startup))
    support = bool(index.get('support_observation'))
    stage = index.get('state') or '趋势数据待补全'
    priority = (0 if index.get('strong_advance') else 1 if online else
                2 if startup else 3 if support else 8 if index else 9)
    reasons = []
    if index:
        reasons.append('同花顺指数趋势：' + stage)
        if index.get('episode_start'):
            reasons.append('本轮趋势起点 ' + index['episode_start'])
        if not live:
            reasons.append('完成日线截至 ' + index['asof'])
        if index.get('risk_reason'):
            reasons.append(index['risk_reason'])
    else:
        reasons.append('最新指数趋势数据未对齐')
    return dict(basis='index-trend', rule_version='board-trend-select-20261028.2',
                eligible=bool(holding and not broad and not auction), tracked=bool(holding and not broad and not auction),
                trend=online, startup=startup, support=support,
                label=stage, phase=stage, priority=priority,
                at=index.get('quote_at') if live else (index.get('asof') + ' 15:00:00' if index else None),
                asof=index.get('asof'), live=live, episode_start=index.get('episode_start'),
                source=index.get('source'), code=index.get('code'),
                ret5=index.get('ret5'), ret20=index.get('ret20'),
                completed_asof=daily.get('asof') if completed else None,
                completed_episode_start=daily.get('episode_start') if completed else None,
                completed_trend=bool(completed and daily.get('trend_online')),
                ma10_previous=index.get('ma10_prev'),
                close=index.get('close'), ma5=index.get('ma5'), ma10=index.get('ma10'), ma20=index.get('ma20'),
                ma20_support_established=index.get('ma20_support_established'),
                first_ma10_break=index.get('first_ma10_break'), buffer_days_left=index.get('buffer_days_left'),
                exit_date=index.get('exit_date'), risk_reason=index.get('risk_reason'),
                reasons=reasons, member_coverage_ready=reliable,
                trigger='指数沿上行MA5、MA10推进；回踩后观察收复与继续抬高。',
                invalidate='已建立的MA20支撑收盘失守则退出；MA10失守超过1ATR或第三个交易日仍未收复则降级或退出。',
                rule='按同花顺指数连续趋势跟踪：启动、推进、回踩、修复、转弱；当日涨幅和情绪分不决定入选。')


def refine_strengths(boards, calendar):
    """Separate established relative leaders from the wider trend watch list."""
    from bisect import bisect_left, bisect_right
    groups = {}
    for b in boards.values():
        st = b['strength']
        if st.get('asof') and numeric(st.get('ret5')):
            groups.setdefault((b['type'], st['asof']), []).append(st['ret5'])
    for values in groups.values():
        values.sort()
    for b in boards.values():
        st = b['strength']
        start, end = st.get('completed_episode_start'), st.get('completed_asof')
        days = sum(start <= d <= end for d in calendar) if start and end else 0
        values = groups.get((b['type'], st.get('asof')), [])
        value = st.get('ret5')
        rank = (100 * (bisect_left(values, value) + (bisect_right(values, value)-bisect_left(values, value)-1)/2)
                / (len(values)-1)) if len(values) > 1 and numeric(value) else None
        checks = dict(
            completed_trend=bool(st.get('completed_trend')),
            completed_days=days >= 2,
            positive_5d=numeric(value) and value > 0,
            relative_leader=rank is not None and rank >= 70,
            above_ma10=numeric(st.get('close')) and numeric(st.get('ma10')) and st['close'] >= st['ma10'],
            ma10_rising=numeric(st.get('ma10')) and numeric(st.get('ma10_previous')) and st['ma10'] > st['ma10_previous'])
        st.update(completed_days=days, relative5_rank=round(rank, 2) if rank is not None else None,
                  relative5_population=len(values), selection_checks=checks,
                  eligible=bool(st.get('tracked') and all(checks.values())),
                  selection_rule='至少2个完成交易日的趋势跟踪；5日涨幅为正且同类前30%；MA10上行，指数守住MA10。')
        if st.get('tracked') and not st['eligible']:
            if not checks['completed_trend'] or not checks['completed_days']:
                st['index_stage'] = st['label']
                st.update(label='启动观察', phase='启动观察', priority=2)
                b.update(status='启动观察', lane='watch', priority=2)
            else:
                b['lane'] = 'waiting'
            labels = dict(completed_trend='尚无完成日趋势基础', completed_days='完成日跟踪不足2日',
                          positive_5d='5日表现尚未转正', relative_leader='5日表现尚未进入同类前30%',
                          above_ma10='指数暂未收回MA10', ma10_rising='MA10尚未向上')
            b['reasons'].append('保留趋势跟踪：' + '、'.join(labels[k] for k, passed in checks.items() if not passed))
        elif st['eligible']:
            b['reasons'].append('完成日跟踪%d日；5日表现同类前%.1f%%；MA10向上且支撑有效' % (days, 100-rank))
        if b.get('timeline') and b['timeline'][-1].get('at') == st.get('at'):
            b['timeline'][-1].update(status=b['status'], lane=b['lane'])


def role_candidates(rows, auction=False):
    result = dict(leader=[], center=[], followers=[],
                  basis='行情观察候选；不代表已核验的产业地位或资金控盘角色。')
    valid = [s for s in rows if s['valid'] and numeric(s['change_pct'])]
    if auction or not valid:
        return result
    sealed = [s for s in valid if s['sealed'] and (s['height'] or 0) >= 2]
    if sealed:
        top = max(s['height'] for s in sealed)
        leaders = sorted([s for s in sealed if s['height'] == top],
                         key=lambda s: -(s['amount_wan'] or 0))[:2]
        result['leader'] = [dict(code=s['code'], reason='板内已核验最高连板 %s 板；并列时看成交额' % top) for s in leaders]
    else:
        trend = [s for s in valid if s['change_pct'] > 0 and s.get('trend_strong')]
        if trend:
            best = max(trend, key=lambda s: (s['trend_score'] or 0, s.get('ret5') or 0))
            result['leader'] = [dict(code=best['code'], reason='趋势领涨候选：个股趋势强势，板内趋势分最高 %.1f' % best['trend_score'])]
    used = {s['code'] for s in result['leader']}
    amount = sorted([s for s in valid if numeric(s['amount_wan']) and s['amount_wan'] > 0],
                    key=lambda s: -s['amount_wan'])
    caps = sorted([s for s in valid if numeric(s.get('float_mcap')) and s['float_mcap'] > 0],
                  key=lambda s: -s['float_mcap'])
    # Market cap is required; large turnover alone never establishes a center candidate.
    cap_top = {s['code'] for s in caps[:max(1, (len(caps)+2)//3)]} if len(caps) >= 3 else set()
    for s in amount[:3]:
        if s['code'] not in used and s['code'] in cap_top and s['change_pct'] >= 0 and (s.get('trend_strong') or s.get('emotion_strong')):
            result['center'] = [dict(code=s['code'], reason='成交额板内前三、流通市值前三分之一，价格未下跌且个股强势；成交额 %.2f 亿元' % (s['amount_wan']/10000))]
            used.add(s['code'])
            break
    follows = [s for s in valid if s['code'] not in used and s['change_pct'] > 0 and
               (s['sealed'] or s.get('trend_strong') or s.get('emotion_strong'))]
    follows.sort(key=lambda s: (-int(s['sealed']), -(s['height'] or 0), -s['change_pct']))
    result['followers'] = [dict(code=s['code'], reason='同板正涨幅且' + ('当前封板' if s['sealed'] else '个股强势') + '；仅表示同步表现') for s in follows]
    return result


def build(snap, persist=True, fetch_news=True):
    now = clock()
    observed = str(now)
    day = str(snap.get('quote_capture_at') or snap.get('generated_at') or '')[:10]
    source_at = snap.get('quote_capture_at') or snap.get('generated_at')
    news = refresh_news() if fetch_news else read(ROOT / 'news.json.gz', {}) or {}
    if persist and fetch_news:
        start_news_worker()
    auction = snap.get('session') in ('盘前', '集合竞价', '竞价结束')
    current_stocks = {str(s['code']): stock(s, day, auction) for key in ('stocks', 'coverage_catalog') for s in snap.get(key) or []}
    catalog = snap.get('board_catalog') or []
    daily_asof = (snap.get('strength_model') or {}).get('asof') or snap.get('daily_asof')
    priorities = [b['name'] for b in catalog if strong_evidence(b, day, True, auction, daily_asof)['eligible']]
    definitions = refresh_definitions(priorities + ['人形机器人', '机器人概念', '比亚迪概念', '一带一路']) if fetch_news else read(ROOT / 'definitions.json.gz', {}) or {}
    dynamics = (snap.get('board_dynamics') or {}).get('by_id') or {}
    prior = read(ROOT / 'days' / (day + '.json.gz'), {}) or {}
    archives = {}
    for path in sorted((ROOT / 'days').glob('????-??-??.json.gz'), reverse=True):
        date = path.name[:10]
        if date < day and len(archives) < MAX_DAYS - 1:
            saved = read(path)
            if saved and saved.get('version') == VERSION:
                archives[date] = saved
    previous_day = archives[max(archives)] if archives else {}
    same_quote = prior.get('source_at') == source_at
    formal = bool(str(snap.get('close_daily_verified_at') or '').startswith(day) and snap.get('session') == '已收盘')
    session = snap.get('session')
    mode = '收盘归档' if formal else '竞价参考' if session in ('盘前', '集合竞价', '竞价结束') else '午休参考' if session == '午间休市' or day == now.date().isoformat() and 690 <= now.hour * 60 + now.minute < 780 else '收盘后·待正式归档' if session in ('已收盘', '收盘后') or day == now.date().isoformat() and now.hour >= 15 else '盘中观察'
    events = news.get('events') or []
    # Historical rebuilds must not attach news learned on a later date.
    news_asof = observed if day == now.date().isoformat() else day + ' 23:59:59'
    boards = {}
    old_boards = prior.get('boards') or {}
    for b in catalog:
        identity = b['id']
        members = sorted(set(str(c) for c in b.get('member_codes') or []))
        rows = [current_stocks[c] for c in members if c in current_stocks]
        relay_valid = [s for s in rows if s['valid']]
        sealed = [s for s in relay_valid if s['sealed']]
        ladder = {}
        for s in sealed:
            ladder.setdefault(str(s['height']) if s['height'] is not None else 'unknown', []).append(s['code'])
        for codes in ladder.values():
            codes.sort(key=lambda c: (-(current_stocks[c].get('amount_wan') or 0), c))
        d = dynamics.get(identity) or {}
        w = {} if auction else d.get('change') or {}
        metric = d.get('current') or {}
        auction_quote = b.get('member_auction') or {}
        if auction:
            metric = dict(return_pct=auction_quote.get('change_pct') if auction_quote.get('ready') else None,
                          up_pct=auction_quote.get('up_pct') if auction_quote.get('ready') else None)
        coverage = len(relay_valid) * 100 / len(members) if members else None
        reliable = len(relay_valid) >= 6 and (coverage or 0) >= 80
        strength = strong_evidence(b, day, reliable, auction, daily_asof)
        lane = ('priority' if strength['eligible'] and strength['priority'] == 0 else
                'waiting' if strength['eligible'] and strength['trend'] else
                'watch' if strength['eligible'] else
                'cooling' if strength['support'] or strength.get('risk_reason') else
                'ordinary' if strength.get('asof') else 'pending')
        status = '竞价参考' if auction else strength['label']
        previous = old_boards.get(identity) or {}
        if same_quote:
            changes = previous.get('changes') or {}
        elif previous and previous.get('members') == members and prior.get('date') == day:
            known = {c for c in members if current_stocks.get(c, {}).get('valid') and (prior.get('stocks', {}).get(c) or {}).get('valid')}
            before = {c for c in known if prior['stocks'][c].get('sealed')}
            after = {c for c in known if current_stocks[c]['sealed']}
            changes = dict(new_sealed=sorted(after - before), opened=sorted(before - after),
                           comparable=len(known), from_at=prior.get('source_at'), to_at=source_at)
        else:
            changes = dict(new_sealed=[], opened=[], comparable=0,
                           note='成员变化，不比较梯队增减' if previous else '首次记录，等待下一次有效报价')
        # Old releases persisted post-close acquisition times as market times.
        # Normalize only the derived timeline; retained source evidence is untouched.
        timeline_by_at = {}
        for entry in (previous.get('timeline') or []) if (previous.get('strength') or {}).get('basis') == 'index-trend' else []:
            at = str(entry.get('at') or '')
            if len(at) < 19:
                continue
            entry_time = at[11:19]
            if entry_time >= '15:00:00':
                at = at[:10] + ' 15:00:00'
            elif not ('09:30:00' <= entry_time <= '11:30:00' or '13:00:00' <= entry_time <= '15:00:00'):
                continue
            timeline_by_at[at] = dict(entry, at=at)
        current_at = strength.get('at') or source_at
        if current_at and str(current_at)[11:19] >= '15:00:00':
            current_at = str(current_at)[:10] + ' 15:00:00'
        earlier = [at for at in timeline_by_at if current_at and at <= current_at]
        last = timeline_by_at[max(earlier)] if earlier else None
        if current_at and (current_at in timeline_by_at or not last or last.get('status') != status):
            timeline_by_at[current_at] = dict(at=current_at, status=status, lane=lane)
        timeline = [timeline_by_at[at] for at in sorted(timeline_by_at) if not current_at or at <= current_at]
        links = news_for(b['name'], members, current_stocks, events, news_asof)
        trend = sorted((s for s in rows if numeric(s['trend_score']) and s['trend_score'] >= 65),
                       key=lambda s: (-s['trend_score'], s['code']))
        amount = sorted((s for s in relay_valid if numeric(s['amount_wan'])),
                        key=lambda s: (-s['amount_wan'], s['code']))
        opened = [s['code'] for s in relay_valid if s['touched'] and not s['sealed']]
        broken = [s['code'] for s in relay_valid if s['prior_sealed'] and (s['prior_height'] or 0) >= 2 and not s['sealed']]
        previous_state = (previous_day.get('boards', {}).get(identity) or {}).get('status')
        boards[identity] = dict(id=identity, name=b['name'], type=b['type'], members=members,
            status=status, lane=lane, tags=[] if not strength.get('asof') else ['盘中趋势' if strength['live'] else '完成日趋势'], priority=strength['priority'],
            definition=definition_for(b, definitions), strength=strength,
            broad=b['type']=='theme' and b['name'] in BROAD_THEMES, size_wide=bool(b.get('wide')),
            role_candidates=role_candidates(rows, auction),
            reasons=strength['reasons'],
            trigger=strength['trigger'], invalidate=strength['invalidate'],
            current=metric, change=w, trend_score=(b.get('market_strength') or {}).get('trend_score'),
            return_pct=metric.get('return_pct', b.get('member_today')),
            auction=auction_quote if auction else None,
            up_pct=metric.get('up_pct') if metric.get('up_pct') is not None else (sum(s['change_pct'] > 0 for s in relay_valid if numeric(s['change_pct'])) * 100 / len(relay_valid) if relay_valid else None), expected=len(members), valid=len(relay_valid),
            coverage_pct=round(coverage, 2) if coverage is not None else None, reliable=reliable,
            source_at=(auction_quote.get('quote_at') or source_at) if auction else d.get('source_at') or b.get('member_quote_at') or source_at,
            limit_count=len(sealed), highest=max((s['height'] or 0 for s in sealed), default=0),
            ladder=ladder, unknown_height=sum(s['height'] is None for s in sealed),
            trend_members=[s['code'] for s in trend], amount_members=[s['code'] for s in amount[:12]],
            opened=opened, broken=broken, changes=changes, timeline=timeline[-12:], previous_state=previous_state,
            overlaps=d.get('overlaps') or [], news=links,
            logic=links[0]['title'] if links else '暂无可核验的相关快讯；成员表现按行情单独观察。',
            membership_basis=b.get('source_basis') or '同花顺成员归属', membership_at=b.get('source_checked_at'),
            membership_stale=b.get('membership_stale'), index_pct=(b.get('index_current') or {}).get('change_pct'))
    refine_strengths(boards, (snap.get('board_trend_model') or {}).get('calendar') or [])
    order = sorted(boards, key=lambda identity: (boards[identity]['priority'],
                   -(boards[identity]['strength'].get('ret5') or 0),
                   -(boards[identity]['strength'].get('ret20') or 0), boards[identity]['name']))
    counts = dict(Counter(b['lane'] for b in boards.values()))
    journal = dict(version=VERSION, date=day, source_at=source_at, observed_at=observed, mode=mode, formal=formal,
                   boards=boards, stocks=current_stocks, order=order, counts=counts,
                   news={k: news.get(k) for k in ('checked_at', 'last_success_at', 'latest_published_at', 'status', 'errors', 'batch_count', 'scope')},
                   relay_coverage=(snap.get('emotion_relay') or {}).get('coverage') or {},
                   summary=[
                       dict(label='趋势推进', ids=[i for i in order if boards[i]['lane'] == 'priority'][:4]),
                       dict(label='启动观察', ids=[i for i in order if boards[i]['lane'] == 'watch'][:4]),
                       dict(label='回踩跟踪', ids=[i for i in order if boards[i]['lane'] == 'waiting'][:4]),
                       dict(label='趋势降级', ids=[i for i in order if boards[i]['lane'] == 'cooling'][:4])])
    if persist and day == now.date().isoformat():
        # Never replace an already verified close with a weaker or older observation.
        if not (prior.get('formal') and not formal) and (not prior or str(source_at) >= str(prior.get('source_at') or '')):
            write(ROOT / 'days' / (day + '.json.gz'), journal)
    matrix = {}
    for date, saved in sorted(dict(archives, **{day: journal}).items()):
        matrix[date] = dict(mode=saved['mode'], source_at=saved['source_at'], boards={
            identity: {k: b.get(k) for k in ('status', 'lane', 'highest', 'limit_count', 'return_pct', 'reliable', 'strength')}
            for identity, b in saved['boards'].items()})
    return dict(version=VERSION, current=journal, dates=sorted(matrix, reverse=True), matrix=matrix, archives=archives)
