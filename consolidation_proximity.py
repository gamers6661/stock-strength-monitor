"""已核验口径的支撑位置提示，不替代反弹确认。"""
from consolidation_tracking import valid_number as number
import config


def observe(setup, context, price, at, exited=False):
    if exited or not at or context.get('valid') is not True or not number(price) or price <= 0:
        return dict(support_alerts=[], support_alert_at=None)
    atr, factor = context.get('atr20'), context.get('scale_factor')
    if not number(atr) or atr <= 0 or not number(factor) or factor <= 0:
        return dict(support_alerts=[], support_alert_at=None)
    bottom = setup.get('platform_low')
    targets = [('平台底部', bottom * factor if number(bottom) else None)]
    targets += [('MA'+str(n), context.get('thresholds', {}).get(n)) for n in (5, 10, 20)]
    alerts = []
    for name, target in targets:
        if not number(target) or target <= 0:
            continue
        distance = (price-target)/atr
        # 跌穿支撑不叫“即将碰到”，失守由跟踪状态说明。
        if -1e-9 <= distance <= config.TREND_CONSOLIDATION['support_alert_atr']+1e-9:
            alerts.append(dict(label=('触及' if abs(distance)<1e-9 else '接近')+name,
                               target=name, price=round(target, 4), distance_atr=round(max(0, distance), 3),
                               distance_pct=round(100*(price/target-1), 3), quote_at=at))
    return dict(support_alerts=alerts, support_alert_at=at,
                support_platform_low=round(targets[0][1], 4) if targets[0][1] else None)
