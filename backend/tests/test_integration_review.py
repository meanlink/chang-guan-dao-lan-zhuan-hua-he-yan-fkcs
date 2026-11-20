"""复盘功能的端到端集成测试（FastAPI + SQLite，需安装 web 依赖）。

与 test_replay.py（纯标准库）分开：本文件验证路由、鉴权、持久化、
样本冻结与 worker 批处理/恢复的真实协作。用临时 SQLite，不依赖
Postgres/Redis；Redis 入队失败被静默兜底，不影响断言。

运行（在 backend/ 下）：
    DATABASE_URL=sqlite:////tmp/review_it.db \
    /path/to/venv/bin/python -m tests.test_integration_review
"""
import os
import tempfile
import unittest

_DB = os.path.join(tempfile.gettempdir(), 'review_it.db')
if os.path.exists(_DB):
    os.remove(_DB)
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + _DB)
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6399/0')  # 无服务，触发兜底
os.environ.setdefault('JWT_SECRET', 'integration-test-secret')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.config.database import Base, engine, Session  # noqa: E402
from src.models import User, FlowEvent, Review  # noqa: E402
from src.routes import auth, flow, reviews  # noqa: E402
from src.services import reviews as review_service  # noqa: E402
from src.services import replay  # noqa: E402
from src.services.flow_seed import seed_flow_events, BUSINESS_DAY, THEN, NOW  # noqa: E402
from src.utils.security import hash_password  # noqa: E402

# 强制跨多个批边界，以验证逐批推进与中断恢复。
replay.BATCH_SIZE = 3


def build_app():
    app = FastAPI()
    for router in (auth.router, flow.router, reviews.router):
        app.include_router(router)
    return app


class ReviewIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        with Session() as db:
            for role, name in [('admin', '负责人'), ('analyst', '分析员'), ('viewer', '观察员')]:
                email = role + '@demo.local'
                if not db.scalar(select(User).where(User.email == email)):
                    db.add(User(email=email, name=name, role=role,
                                password=hash_password('Demo123!')))
            db.commit()
        cls.app = build_app()
        cls._client = TestClient(cls.app)
        cls.tokens = {}

    def client(self):
        return self._client

    def login(self, role):
        if role not in self.tokens:
            r = self.client().post('/auth/login',
                                   json={'email': role + '@demo.local', 'password': 'Demo123!'})
            self.assertEqual(r.status_code, 200, r.text)
            self.tokens[role] = r.json()['access_token']
        return {'Authorization': 'Bearer ' + self.tokens[role]}

    def test_01_seed_events_and_dedup(self):
        headers = self.login('admin')
        c = self.client()
        for e in seed_flow_events():
            r = c.post('/flow-events', json=e, headers=headers)
            self.assertEqual(r.status_code, 201, r.text)
        # 同号同类同收讫时间重复登记 -> 409
        dup = dict(seed_flow_events()[0])
        r = c.post('/flow-events', json=dup, headers=headers)
        self.assertEqual(r.status_code, 409)
        # 缺字段 -> 422
        bad = dict(dup); del bad['flow_no']
        r = c.post('/flow-events', json=bad, headers=headers)
        self.assertEqual(r.status_code, 422)
        r = c.get('/flow-events', headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), len(seed_flow_events()))

    def test_02_viewer_cannot_ingest_or_create(self):
        headers = self.login('viewer')
        c = self.client()
        r = c.post('/flow-events', json=seed_flow_events()[0], headers=headers)
        self.assertEqual(r.status_code, 403)
        payload = {'name': '无权复盘', 'business_date': BUSINESS_DAY,
                   'zone': '全部', 'as_of_then': THEN}
        r = c.post('/reviews', json=payload, headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_03_create_review_freezes_sample(self):
        headers = self.login('analyst')
        c = self.client()
        payload = {'name': '导览试点复盘', 'business_date': BUSINESS_DAY,
                   'zone': '全部', 'as_of_then': THEN, 'as_of_now': NOW}
        r = c.post('/reviews', json=payload, headers=headers)
        self.assertEqual(r.status_code, 201, r.text)
        review = r.json()
        self.__class__.review_id = review['id']
        # 样本在创建瞬间圈定，包含全部 seed 事件
        self.assertEqual(review['sample_size'], len(seed_flow_events()))
        self.assertEqual(review['status'], 'queued')
        self.assertEqual(review['cursor'], 0)

    def test_04_worker_resumable_batches_and_conclusions(self):
        rid = self.__class__.review_id
        # 模拟 worker：逐批推进，中间制造一次“崩溃恢复”。
        with Session() as db:
            rv = db.get(Review, rid)
            review_service.run_batch(db, rv)  # 第一批
            self.assertEqual(rv.status, 'running')
            db.commit()
            first_cursor = rv.cursor
            self.assertGreater(first_cursor, 0)
            self.assertLess(first_cursor, len(rv.event_ids))
        # 重启 worker：从持久化的 cursor/中间状态续算直到完成。
        with Session() as db:
            rv = db.get(Review, rid)
            guard = 0
            while rv.status != 'completed':
                review_service.run_batch(db, rv)
                db.commit()
                guard += 1
                self.assertLess(guard, 50)
            self.assertEqual(rv.status, 'completed')
            self.assertEqual(rv.progress, 1.0)
            self.assertEqual(rv.cursor, len(rv.event_ids))
            self.assertEqual(rv.result['then']['visitors'], 408)
            self.assertEqual(rv.result['now']['visitors'], 415)
            self.assertEqual(rv.result['difference']['visitors_delta'], 7)
            self.assertEqual(rv.result['difference']['changed_records'], 4)

    def test_05_concurrent_supplement_cannot_invade_frozen_sample(self):
        rid = self.__class__.review_id
        headers = self.login('admin')
        # 复盘完成后才到达的并发补报：写入台账，但不改变已冻结复盘。
        late = {'flow_no': 'F-7777', 'zone': '星空厅', 'business_date': BUSINESS_DAY,
                'event_type': 'supplement', 'visitors': 999,
                'received_at': NOW + 3600, 'note': '复盘后并发补报'}
        c = self.client()
        r = c.post('/flow-events', json=late, headers=headers)
        self.assertEqual(r.status_code, 201, r.text)
        detail = c.get('/reviews/' + str(rid), headers=headers).json()
        self.assertEqual(detail['result']['now']['visitors'], 415)  # 维持冻结结论
        self.assertNotIn('F-7777', detail['result']['now']['flow_numbers'])

    def test_06_retry_resumes_same_review_same_sample(self):
        headers = self.login('analyst')
        c = self.client()
        # 新建一个复盘，跑一半置 failed 模拟中断，再用 retry 续算到完成。
        payload = {'name': '中断恢复复盘', 'business_date': BUSINESS_DAY,
                   'zone': '全部', 'as_of_then': THEN, 'as_of_now': NOW}
        rid = c.post('/reviews', json=payload, headers=headers).json()['id']
        with Session() as db:
            rv = db.get(Review, rid)
            review_service.run_batch(db, rv)
            rv.status = 'failed'; rv.error = '模拟中断'
            db.commit()
            frozen_ids = list(rv.event_ids)
        r = c.post('/reviews/' + str(rid) + '/retry', headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'queued')
        # 已完成的复盘不允许重试
        done = c.post('/reviews/' + str(self.__class__.review_id) + '/retry',
                      headers=headers)
        self.assertEqual(done.status_code, 409)
        with Session() as db:
            rv = db.get(Review, rid)
            while rv.status != 'completed':
                review_service.run_batch(db, rv)
                db.commit()
            self.assertEqual(rv.event_ids, frozen_ids)          # 不换样本
            self.assertEqual(rv.result['now']['visitors'], 415)  # 同口径同结论

    def test_07_invalid_cutoff_rejected(self):
        headers = self.login('analyst')
        c = self.client()
        # “当时”不早于“今天”冻结时点
        r = c.post('/reviews', json={
            'name': '非法时点', 'business_date': BUSINESS_DAY, 'zone': '全部',
            'as_of_then': NOW, 'as_of_now': THEN}, headers=headers)
        self.assertEqual(r.status_code, 422)


if __name__ == '__main__':
    unittest.main(verbosity=2)
