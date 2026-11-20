from pydantic import BaseModel, Field


class FlowEventInput(BaseModel):
    flow_no: str = Field(min_length=1, max_length=64)
    zone: str = Field(min_length=1, max_length=80)
    business_date: str = Field(min_length=10, max_length=10)
    event_type: str = Field(min_length=1, max_length=16)
    visitors: int = Field(ge=0)
    received_at: float
    note: str = Field(default='', max_length=200)


class ReviewInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    business_date: str = Field(min_length=10, max_length=10)
    zone: str = Field(default='全部', max_length=80)
    as_of_then: float                       # 选定的过去收讫时点
    as_of_now: float | None = None          # 缺省取服务端当前时间并冻结
