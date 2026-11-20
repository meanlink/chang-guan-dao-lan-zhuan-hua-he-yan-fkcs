from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class ReviewStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class FlowEventType(str, Enum):
    # 首报 / 补报 / 更正 / 撤销；每条都登记实际收讫时间 received_at
    report = 'report'
    supplement = 'supplement'
    correction = 'correction'
    retract = 'retract'
