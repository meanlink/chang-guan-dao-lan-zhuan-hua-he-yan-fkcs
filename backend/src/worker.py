import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, Review
from src.services.business import analyze
from src.services.reports import deliver
from src.services import reviews
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def execute_review(review_id):
    # 每批独立事务提交进度；崩溃后由 recover 重新入队，从 cursor 断点续算。
    with Session() as db:
        r=db.get(Review,review_id)
        if not r or r.status=='completed':return
        r.status='running';db.commit()
        try:
            reviews.run_batch(db,r)
            if r.status=='completed':
                record(db,'worker','review.completed',{'id':r.id,'sample':len(r.event_ids)})
            db.commit()
        except Exception as e:
            db.rollback()
            logging.exception('Review batch failed')
            with Session() as fail_db:
                rr=fail_db.get(Review,review_id)
                if rr:
                    rr.status='failed';rr.error=str(e)[:990]
                    record(fail_db,'worker','review.failed',{'id':rr.id,'error':rr.error})
                    fail_db.commit()
            return
    # 还有剩余批次则继续入队推进，保持“同一复盘、同一样本”。
    if r.status=='running':
        reviews.enqueue(r.id)
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        review_ids=list(db.scalars(select(Review.id).where(Review.status=='queued').limit(3)))
    for review_id in review_ids:execute_review(review_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        # 复盘同样在批边界恢复：running 视为未完成，重新排队从 cursor 续算。
        for rv in db.scalars(select(Review).where(Review.status=='running')):
            rv.status='queued';record(db,'worker','review.recovered',{'id':rv.id,'cursor':rv.cursor})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            item=r.blpop('review:queue',timeout=1)
            if item:execute_review(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
