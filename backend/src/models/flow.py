from sqlalchemy import String, Double, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base

class FlowEvent(Base):
    """分区客流的双时间事件。

    business_date 是事件归属的营业日（有效时间）；received_at 是馆方实际
    收讫时间（交易时间）。补报、更正、撤销都新增一行，永不原地覆盖，因此
    任意历史时点的口径都可按 received_at 重放还原。
    """
    __tablename__ = 'flow_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    flow_no: Mapped[str] = mapped_column(String(64))            # 同号记录的自然键
    zone: Mapped[str] = mapped_column(String(80))
    business_date: Mapped[str] = mapped_column(String(10))      # YYYY-MM-DD
    event_type: Mapped[str] = mapped_column(String(16))         # report/supplement/correction/retract
    visitors: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[float] = mapped_column(Double)          # 实际收讫时间（秒）
    note: Mapped[str] = mapped_column(String(200), default='')

Index('ix_flow_events_received', FlowEvent.received_at)
Index('ix_flow_events_flow_no', FlowEvent.flow_no)
