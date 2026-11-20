from fastapi import APIRouter, Depends
from sqlalchemy import select
from src.config.database import get_db
from src.models import FlowEvent
from src.schemas.review import FlowEventInput
from src.middlewares.auth import current_user, can_write
from src.services import flow
from src.services.audit import record
router = APIRouter(prefix='/flow-events')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [flow.event_dict(e) for e in flow.list_events(db)]


@router.post('', status_code=201)
def create(data: FlowEventInput, db=Depends(get_db), u=Depends(can_write)):
    e = flow.create_event(db, data)
    record(db, u.email, 'flow.ingest',
           {'flow_no': e.flow_no, 'type': e.event_type, 'received_at': e.received_at})
    db.commit()
    return flow.event_dict(e)
