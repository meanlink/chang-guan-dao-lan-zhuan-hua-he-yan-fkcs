"""导览试点复盘的双时间重放引擎（仅依赖标准库）。

口径
----
每条客流事件都带：
  * business_date：归属营业日（有效时间）；
  * received_at ：馆方实际收讫时间（交易时间）。
给定一个收讫时点 cutoff，仅纳入 received_at <= cutoff 的事件，按 flow_no
依收讫顺序归并出该时点“当时所知”的有效记录：
  * report/supplement：建立或更新该号记录的进区人数；
  * correction       ：可把同号记录挪到另一个营业日（business_date 改变），
                        并更新人数；
  * retract          ：撤销该号记录，之后不再计入客流。

引擎不触碰数据库，输入为普通 dict 列表，便于单测与中断恢复。
"""
from __future__ import annotations

VALID_TYPES = ('report', 'supplement', 'correction', 'retract')
# 单次批处理的样本条数；落库后即可在该边界安全中断/恢复。
BATCH_SIZE = 25


def validate_event(event: dict) -> None:
    """校验单条事件，非法即抛 ValueError，绝不静默伪造数据。"""
    required = ('flow_no', 'zone', 'business_date', 'event_type', 'visitors', 'received_at')
    for key in required:
        if event.get(key) is None or event.get(key) == '':
            raise ValueError(f'客流事件缺少字段 {key}')
    if event['event_type'] not in VALID_TYPES:
        raise ValueError(f"未知事件类型 {event['event_type']}")
    try:
        visitors = int(event['visitors'])
        received = float(event['received_at'])
    except (TypeError, ValueError):
        raise ValueError('进区人数与收讫时间必须为数值')
    if visitors < 0 or visitors != float(event['visitors']):
        raise ValueError('进区人数必须为非负整数')
    if received != received or received in (float('inf'), float('-inf')):
        raise ValueError('收讫时间必须为有限数值')
    if not isinstance(event['business_date'], str) or len(event['business_date']) != 10:
        raise ValueError('营业日必须为 YYYY-MM-DD')


def _blank_state() -> dict:
    # flow_no -> 当前有效记录；retract 后从 dict 移除
    return {'records': {}, 'processed': 0}


def apply_event(state: dict, event: dict, business_date: str, zone: str) -> None:
    """把一条已通过 cutoff/范围筛选的事件并入归并状态（原地修改）。"""
    flow_no = event['flow_no']
    kind = event['event_type']
    if kind == 'retract':
        state['records'].pop(flow_no, None)
        return
    if kind == 'correction':
        # 更正允许把同号记录挪到另一个营业日；以事件自带的新归属为准。
        record = state['records'].get(flow_no, {})
        record['flow_no'] = flow_no
        record['zone'] = event['zone']
        record['business_date'] = event['business_date']
        record['visitors'] = int(event['visitors'])
        state['records'][flow_no] = record
        return
    # report / supplement：同号补报累加进区人数，首报建立记录。
    record = state['records'].get(flow_no)
    if record is None:
        record = {'flow_no': flow_no, 'zone': event['zone'],
                  'business_date': event['business_date'], 'visitors': 0}
        state['records'][flow_no] = record
    record['visitors'] += int(event['visitors'])


def in_scope(event: dict, cutoff: float) -> bool:
    """事件是否落入某次核验的收讫范围。

    只按收讫时点过滤，不按营业日/展区预过滤——更正可能把同号记录挪到
    另一个营业日或另一个展区，必须先消费这类事件；营业日与展区归属都在
    归并后的有效记录上再判定（见 active_rows/summarize）。
    """
    return float(event['received_at']) <= cutoff


def replay(events: list[dict], business_date: str, zone: str, cutoff: float,
           state: dict | None = None, limit: int | None = None) -> dict:
    """按 cutoff 重放事件，归并出该时点的有效客流记录。

    state 可传入上一批的中间状态以续算；limit 限制本批消费的事件数，
    返回的 state 含 processed（累计已消费条数），供断点恢复。
    调用方应保证 events 已按 (received_at, id) 稳定排序。
    business_date 与 zone 仅用于最终汇总，不参与事件预过滤（见 in_scope）。
    """
    if state is None:
        state = _blank_state()
    consumed = 0
    for event in events[state['processed']:]:
        if limit is not None and consumed >= limit:
            break
        validate_event(event)
        if in_scope(event, cutoff):
            apply_event(state, event, business_date, zone)
        state['processed'] += 1
        consumed += 1
    return state


def active_rows(state: dict, business_date: str, zone: str) -> list[dict]:
    """归并状态中仍归属目标营业日/展区的有效记录（更正可能已把同号挪走）。"""
    return [dict(r) for r in state['records'].values()
            if r['business_date'] == business_date
            and (zone == '全部' or r['zone'] == zone)]


def all_records_map(state: dict) -> dict:
    """全部营业日的 flow_no→有效记录映射，供差异判定区分挪日与撤销。"""
    return {flow_no: dict(r) for flow_no, r in state['records'].items()}


def summarize(state: dict, business_date: str, zone: str, cutoff: float) -> dict:
    """把归并状态汇总成一次核验结论。"""
    rows = active_rows(state, business_date, zone)
    visitors = sum(int(r['visitors']) for r in rows)
    by_zone: dict[str, int] = {}
    for r in rows:
        by_zone[r['zone']] = by_zone.get(r['zone'], 0) + int(r['visitors'])
    return {
        'cutoff': cutoff,
        'business_date': business_date,
        'zone': zone,
        'active_records': len(rows),
        'visitors': visitors,
        'by_zone': [{'zone': z, 'visitors': v} for z, v in sorted(by_zone.items())],
        'flow_numbers': sorted(r['flow_no'] for r in rows),
        'rows': sorted(rows, key=lambda r: r['flow_no']),
    }


def diff_conclusions(then_rows: list[dict], now_rows: list[dict],
                     then_summary: dict, now_summary: dict,
                     then_all: dict | None = None,
                     now_all: dict | None = None) -> dict:
    """对比当时与今天两次结论，定位造成差异的同号记录。

    then_rows/now_rows 是目标营业日口径的有效记录（用于人数勾稽）；
    then_all/now_all 是全部营业日的 flow_no→记录 映射，用于区分
    “更正挪到另一营业日”与“记录被撤销”——两者在目标日视图里都会消失。
    """
    then_map = {r['flow_no']: r for r in then_rows}
    now_map = {r['flow_no']: r for r in now_rows}
    then_all = then_all or {}
    now_all = now_all or {}
    details = []
    for flow_no in sorted(set(then_map) | set(now_map)):
        a, b = then_map.get(flow_no), now_map.get(flow_no)
        if a == b:
            continue
        reasons = []
        if a is None:
            reasons.append('补报进入收讫范围')
        elif b is None:
            # 目标日视图里消失：借全量状态判断是挪走还是彻底撤销。
            if flow_no in now_all:
                reasons.append('更正挪至另一营业日')
            else:
                reasons.append('记录被撤销')
        else:
            if a['business_date'] != b['business_date']:
                reasons.append('更正挪至另一营业日')
            if a['visitors'] != b['visitors']:
                reasons.append('补报/更正改变进区人数')
            if a['zone'] != b['zone']:
                reasons.append('更正改变展区')
        details.append({
            'flow_no': flow_no,
            'then': a,
            'now': b,
            'reasons': reasons,
            'delta_visitors': (b['visitors'] if b else 0) - (a['visitors'] if a else 0),
        })
    return {
        'visitors_delta': now_summary['visitors'] - then_summary['visitors'],
        'record_count_delta': now_summary['active_records'] - then_summary['active_records'],
        'changed_records': len(details),
        'details': details,
    }
