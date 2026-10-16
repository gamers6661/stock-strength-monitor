# -*- coding: utf-8 -*-
"""验收截图 —— 无头 Chrome 逐页出图

关键坑（记一次）：入场动画用 animation-fill-mode:both 时，无头模式下
--virtual-time-budget 不推进动画，元素停在 opacity:0，整页看起来是灰的/空的，
那是假象。所以必须注入 *{animation:none!important;transition:none!important}，
让所有元素直接落到终态。
"""
import io
import os
import subprocess
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dashboard.html")

# (文件名, 进入的页签, 额外 JS, 视口高)
PAGES = [
    ("01_总览", "overview", "", 2600),
    ("02_每日分析", "overview", "", 1500),
    ("03_个股筛选", "stocks", "", 2100),
    ("04_板块", "boards", "", 2600),
    ("05_题材", "themes", "", 2400),
    ("06_持仓体检", "hold", "", 1500),
    # 联动验证：拿题材组榜第 1 名走一遍"点题材 → 筛个股"的完整链路
    ("07_联动_题材筛选", "stocks",
     "var t=(DATA.theme_rank||[])[0];if(t){pickThemeByName(t.name);}", 2100),
    # 联动验证：板块明细抽屉（含底部"筛选全部成分股"按钮）
    ("08_联动_板块抽屉", "boards",
     "var b=(DATA.boards||[])[0];if(b){showBoardByName(b.idx_code||'');}", 1900),
    # 板别：只筛沪主板（池内板别），验证板别筛选与徽标
    ("09_板别筛选_沪主板", "stocks",
     "clearFilters();STATE.filters.boards=['沪主板'];renderStocks();", 2100),
    # 拥挤度：只看距 MA20 已 >2.5 ATR 的（V2.2 新增因子的核心用途）
    ("10_拥挤度筛选", "stocks",
     "clearFilters();STATE.cols.extra=true;renderStocks();", 2100),
    # 筛选面板（板别多选 + Risk Gate 披露）
    ("11_筛选面板", "stocks", "renderFilterPanel();", 1900),
    # V2.2 个股详情：六因子雷达 + 辅助口径
    ("12_个股详情_因子结构", "stocks",
     "var t=(DATA.stocks||[])[0];if(t){showStock(t.code);}", 2600),
    # 选股雷达：A 档（重点观察）
    ("14_选股雷达_A档", "radar", "setRadarTier('A');", 2200),
    # 启动首日：个股榜（Ignition-1）
    ("16_启动首日_个股榜", "stocks", "setStrategy('ignition');", 2200),
    # 启动首日：选股雷达 A 档
    ("17_启动首日_雷达A档", "radar", "setStrategy('ignition');setRadarTier('A');", 2200),
    # 启动首日：个股详情（因子结构 = 六启动因子）
    ("18_启动首日_详情", "stocks",
     "setStrategy('ignition');var t=(DATA.stocks||[]).filter(function(s){return s.ign_pass;})[0];if(t)showStock(t.code);", 2600),
    # 选股雷达：B 档（数量最多，能看出注释的多样性）
    ("15_选股雷达_B档", "radar", "setRadarTier('B');", 2400),
    # 悬浮说明气泡：验证它浮在卡片之外、不压住卡片自己的标签、不被容器裁掉。
    # 末尾那行内联 visibility 是**无头渲染的权宜**：类切换的可见性变更在这个
    # 截图管线里不会被提交（computed style 已是 visible，但像素没变），
    # 只有内联改动才画得出来。真实浏览器 hover 走的是类切换，正常。
    ("13_悬浮说明_气泡", "stocks",
     "var t=(DATA.stocks||[])[0];if(t){showStock(t.code);}"
     "var el=document.querySelector('.metric .tip');"
     "if(el){el.closest('.metric').scrollIntoView({block:'center'});showTip(el);"
     "document.querySelector('.tipbox').style.visibility='visible';}", 1500),
]


def build_variant(name, pane, extra):
    h = io.open(SRC, encoding="utf-8").read()
    css = ("<style>*{animation:none!important;transition:none!important;"
           "animation-delay:0s!important}</style>")
    js = ("<script>window.addEventListener('load',function(){setTimeout(function(){"
          "try{goPane('%s')}catch(e){}" % pane
          + (("try{%s}catch(e){console.error(e)}" % extra) if extra else "")
          + "try{auditSticky()}catch(e){};window.__ready=1;},150)});</script>")
    h = h.replace("</head>", css + "</head>")
    h = h.replace("</body>", js + "</body>")
    p = os.path.join(HERE, "_shot_%s.html" % name)
    io.open(p, "w", encoding="utf-8").write(h)
    return p


def shoot(path, out, w=1560, hgt=2400):
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1",
           "--window-size=%d,%d" % (w, hgt),
           "--virtual-time-budget=7000",
           "--screenshot=" + out, "file:///" + path.replace("\\", "/")]
    subprocess.run(cmd, capture_output=True, timeout=150)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    pv = os.path.join(HERE, "preview")
    os.makedirs(pv, exist_ok=True)
    for name, pane, extra, tall in PAGES:
        if only and only not in name:
            continue
        p = build_variant(name, pane, extra)
        out = os.path.join(pv, "%s.png" % name)
        shoot(p, out, hgt=tall)
        ok = os.path.exists(out)
        print("[SHOT]", name, "->", os.path.join("preview", os.path.basename(out)),
              (str(os.path.getsize(out)) + "B") if ok else "FAIL")


if __name__ == "__main__":
    main()
