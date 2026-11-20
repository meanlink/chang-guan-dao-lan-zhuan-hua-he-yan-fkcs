from sqlalchemy import String, Double, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base

class Review(Base):
    """导览试点复盘。

    一次复盘固定一个营业日、两个收讫时点（当时 as_of_then / 今天 as_of_now），
    并在创建时圈定样本（event_ids）。重试沿用同一复盘与同一样本，不另开、不换样。
    计算按批次推进，cursor 与 progress 落库以支持中断恢复。
    """
    __tablename__ = 'reviews'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    business_date: Mapped[str] = mapped_column(String(10))
    zone: Mapped[str] = mapped_column(String(80), default='全部')
    as_of_then: Mapped[float] = mapped_column(Double)   # 选定的过去收讫时点
    as_of_now: Mapped[float] = mapped_column(Double)    # 创建复盘时冻结的“今天”时点
    status: Mapped[str] = mapped_column(String(20), default='queued')
    event_ids: Mapped[list] = mapped_column(JSON, default=list)   # 已圈定的收讫范围（样本）
    cursor: Mapped[int] = mapped_column(default=0)                # 已处理到样本的下标
    progress: Mapped[float] = mapped_column(Double, default=0.0)  # 0~1
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
