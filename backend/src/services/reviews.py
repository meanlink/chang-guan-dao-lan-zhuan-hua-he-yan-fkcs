"""复盘的创建、样本圈定与可恢复重放。"""
import time
import json
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Review, FlowEvent
from src.services import replay

ZONES = ('全部', '星空厅', '水世界', '机械坊')


def enqueue(review_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('review:queue', review_id)
        r.close()
    except Exception:
        pass  # SQL queued 状态是持久兜底，worker tick 会捞起


def _frozen_sample(db, business_date: str, as_of_now: float):
    """圈定收讫范围：创建复盘那一刻、收讫时间不晚于“今天”时点的全部事件。

    只冻结事件主键与收讫顺序；后续即便有并发补报写入新事件，也不会进入
    本次复盘，两侧核验都各自守住这条已圈定的范围（样本不换样）。
    """
    rows = db.scalars(
        select(FlowEvent)
        .where(FlowEvent.received_at <= as_of_now)
        .order_by(FlowEvent.received_at, FlowEvent.id)).all()
    return [e.id for e in rows]


def create(db, data, user):
    if data.zone not in ZONES:
        raise HTTPException(422, '未知展区')
    if len(data.business_date) != 10:
        raise HTTPException(422, '营业日必须为 YYYY-MM-DD')
    now = time.time()
    # “今天所知”的收讫时点在创建瞬间冻结；显式传入仅用于对齐演示/复算。
    as_of_now = float(data.as_of_now) if data.as_of_now is not None else now
    if not (data.as_of_then < now):
        raise HTTPException(422, '“当时”时点必须是一个过去时点')
    if data.as_of_then >= as_of_now:
        raise HTTPException(422, '“当时”时点须早于“今天所知”的冻结时点')
    event_ids = _frozen_sample(db, data.business_date, as_of_now)
    if not event_ids:
        raise HTTPException(422, '圈定收讫范围为空：该冻结时点之前没有任何客流事件')
    review = Review(
        name=data.name.strip(), business_date=data.business_date, zone=data.zone,
        as_of_then=float(data.as_of_then), as_of_now=float(as_of_now),
        event_ids=event_ids, cursor=0, progress=0.0, status='queued',
        result={}, error='', created_by=user.id, created_at=now)
    db.add(review)
    db.flush()
    return review


def _load_sample(db, review: Review):
    if not review.event_ids:
        return []
    events = db.scalars(select(FlowEvent).where(FlowEvent.id.in_(review.event_ids))).all()
    by_id = {e.id: e for e in events}
    ordered = [by_id[i] for i in review.event_ids if i in by_id]
    return [{'id': e.id, 'flow_no': e.flow_no, 'zone': e.zone,
             'business_date': e.business_date, 'event_type': e.event_type,
             'visitors': e.visitors, 'received_at': e.received_at} for e in ordered]


def run_batch(db, review: Review):
    """推进一个批次；可被 worker 反复调用直到 completed，天然支持中断恢复。

    两侧核验（当时/今天）在同一批样本上各自维护独立归并状态，进度按样本
    消费比例落库。重试从 review.cursor 续算，不重置、不换样本。
    """
    if review.status == 'completed':
        return review
    review.status = 'running'
    review.error = ''
    events = _load_sample(db, review)
    total = len(events)
    then_state, now_state = review.result.get('_then_state'), review.result.get('_now_state')
    then_state = then_state or replay._blank_state()
    now_state = now_state or replay._blank_state()

    start = review.cursor
    end = min(start + replay.BATCH_SIZE, total)
    # 传全量样本，引擎按各自状态内的 processed 自行切片；本批最多推进到 end。
    replay.replay(events, review.business_date, review.zone, review.as_of_then,
                  state=then_state, limit=end - then_state['processed'])
    replay.replay(events, review.business_date, review.zone, review.as_of_now,
                  state=now_state, limit=end - now_state['processed'])
    review.cursor = end
    review.progress = round(end / total, 6) if total else 1.0

    if end >= total:
        then_rows = replay.active_rows(then_state, review.business_date, review.zone)
        now_rows = replay.active_rows(now_state, review.business_date, review.zone)
        then_summary = replay.summarize(then_state, review.business_date, review.zone,
                                        review.as_of_then)
        now_summary = replay.summarize(now_state, review.business_date, review.zone,
                                       review.as_of_now)
        difference = replay.diff_conclusions(
            then_rows, now_rows, then_summary, now_summary,
            then_all=replay.all_records_map(then_state),
            now_all=replay.all_records_map(now_state))
        review.result = {
            'then': then_summary, 'now': now_summary, 'difference': difference,
            'sample_size': total,
        }
        # 严格 JSON 自检，拒绝 NaN/Inf 等不可序列化结果。
        json.dumps(review.result, allow_nan=False)
        review.status = 'completed'
        review.progress = 1.0
        review.finished_at = time.time()
    else:
        # 仅持久化中间归并状态，供下一批续算。
        review.result = {'_then_state': then_state, '_now_state': now_state}
    return review


def review_dict(r: Review):
    return {'id': r.id, 'name': r.name, 'business_date': r.business_date, 'zone': r.zone,
            'as_of_then': r.as_of_then, 'as_of_now': r.as_of_now, 'status': r.status,
            'progress': r.progress, 'cursor': r.cursor, 'sample_size': len(r.event_ids),
            'result': r.result, 'error': r.error, 'created_at': r.created_at,
            'finished_at': r.finished_at}
