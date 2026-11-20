from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Review
from src.schemas.review import ReviewInput
from src.middlewares.auth import current_user, can_write
from src.services import reviews
from src.services.audit import record
router = APIRouter(prefix='/reviews')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = db.scalars(select(Review).order_by(Review.id.desc()).limit(100))
    return [reviews.review_dict(r) for r in rows]


@router.post('', status_code=201)
def create(data: ReviewInput, db=Depends(get_db), u=Depends(can_write)):
    r = reviews.create(db, data, u)
    record(db, u.email, 'review.create',
           {'id': r.id, 'business_date': r.business_date, 'sample': len(r.event_ids)})
    db.commit()
    reviews.enqueue(r.id)
    return reviews.review_dict(r)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    r = db.get(Review, id)
    if not r:
        raise HTTPException(404, '复盘不存在')
    return reviews.review_dict(r)


@router.post('/{id}/retry')
def retry(id: int, db=Depends(get_db), u=Depends(can_write)):
    # 重试不另开复盘、不换样本：仅把失败/中断的同一复盘重新入队，从断点续算。
    r = db.get(Review, id)
    if not r:
        raise HTTPException(404, '复盘不存在')
    if r.status == 'completed':
        raise HTTPException(409, '复盘已完成，无需重试')
    r.status = 'queued'
    r.error = ''
    record(db, u.email, 'review.retry', {'id': r.id, 'cursor': r.cursor})
    db.commit()
    reviews.enqueue(r.id)
    return reviews.review_dict(r)
