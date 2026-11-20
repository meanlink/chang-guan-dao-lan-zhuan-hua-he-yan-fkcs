"""导览试点复盘的确定性演示数据。

模拟一个营业日（2026-11-06）的分区客流台账，刻意植入四类双时间情形，
每条事件都带实际收讫时间 received_at：
  * 首报当日收讫；
  * 补报在“当时”时点之后才收讫（当时看不到、今天看得到）；
  * 更正把同号记录挪到另一个营业日；
  * 撤销一条已收讫记录。
固定锚点时间，保证再次 seed 与重放结论完全一致。
"""
from __future__ import annotations
from datetime import datetime, timezone

ZONES = ('星空厅', '水世界', '机械坊')
BUSINESS_DAY = '2026-11-06'
NEXT_DAY = '2026-11-07'


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


# 演示用的两个收讫时点（也是复盘页面默认值）。
THEN = _ts('2026-11-06T12:00:00+00:00')   # 当时：当日午间盘点
NOW = _ts('2026-11-10T09:00:00+00:00')    # 今天所知：数日后收口


def seed_flow_events():
    """返回确定性的客流事件列表（dict），顺序即收讫顺序。"""
    rows = []

    def add(flow_no, zone, business_date, event_type, visitors, received, note=''):
        rows.append({'flow_no': flow_no, 'zone': zone, 'business_date': business_date,
                     'event_type': event_type, 'visitors': visitors,
                     'received_at': _ts(received), 'note': note})

    # 1) 三条当日首报，午间盘点前已收讫——当时与今天都可见。
    add('F-1001', '星空厅', BUSINESS_DAY, 'report', 120, '2026-11-06T09:10:00+00:00', '开馆首报')
    add('F-1002', '水世界', BUSINESS_DAY, 'report', 200, '2026-11-06T09:25:00+00:00', '开馆首报')
    add('F-1003', '机械坊', BUSINESS_DAY, 'report', 88, '2026-11-06T10:05:00+00:00', '开馆首报')

    # 2) 同号补报：午间盘点后才收讫——当时不计入，今天计入。
    add('F-1002', '水世界', BUSINESS_DAY, 'supplement', 35, '2026-11-06T14:40:00+00:00', '午后补报')
    add('F-1001', '星空厅', BUSINESS_DAY, 'supplement', 18, '2026-11-07T08:30:00+00:00', '次日补报')

    # 3) 更正：把 F-1003 从 11-06 挪到 11-07（同号记录挪到另一营业日）。
    add('F-1003', '机械坊', NEXT_DAY, 'correction', 90, '2026-11-07T10:15:00+00:00', '日期归属更正')

    # 4) 撤销：F-1004 首报后又撤销（都在“今天”时点前；首报在当时之后，故当时本就不可见）。
    add('F-1004', '机械坊', BUSINESS_DAY, 'report', 60, '2026-11-06T16:20:00+00:00', '临收馆补首报')
    add('F-1004', '机械坊', BUSINESS_DAY, 'retract', 0, '2026-11-08T11:00:00+00:00', '重复登记撤销')

    # 5) 一条纯增量补报（新号），仅今天可见，用于体现记录数差异。
    add('F-1005', '星空厅', BUSINESS_DAY, 'report', 42, '2026-11-09T09:30:00+00:00', '迟到的新号首报')

    return rows
