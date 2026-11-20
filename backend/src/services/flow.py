import time
from fastapi import HTTPException
from sqlalchemy import select
from src.models import FlowEvent
from src.services.replay import validate_event

# (flow_no, event_type, received_at) 构成事件自然键，重复补报不重复入账。
def _natural_key(e: FlowEvent):
    return (e.flow_no, e.event_type, round(e.received_at, 6))


def create_event(db, data):
    payload = data.model_dump()
    try:
        validate_event(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    visitors = int(payload['visitors'])
    received = float(payload['received_at'])
    exists = db.scalar(
        select(FlowEvent).where(
            FlowEvent.flow_no == payload['flow_no'],
            FlowEvent.event_type == payload['event_type'],
            FlowEvent.received_at == received))
    if exists:
        raise HTTPException(409, '同一收讫时间的同号同类事件已登记，请勿重复补报')
    event = FlowEvent(
        flow_no=payload['flow_no'], zone=payload['zone'],
        business_date=payload['business_date'], event_type=payload['event_type'],
        visitors=visitors, received_at=received, note=(payload.get('note') or '')[:200])
    db.add(event)
    db.flush()
    return event


def list_events(db, limit: int = 1000):
    return list(db.scalars(
        select(FlowEvent).order_by(FlowEvent.received_at, FlowEvent.id).limit(limit)))


def event_dict(e: FlowEvent):
    return {'id': e.id, 'flow_no': e.flow_no, 'zone': e.zone,
            'business_date': e.business_date, 'event_type': e.event_type,
            'visitors': e.visitors, 'received_at': e.received_at, 'note': e.note}
