from app.database import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

class JobApplication(Base):
    """申请记录表"""
    __tablename__ = "job_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)

    # 申请状态
    application_status = Column(String(50), default="pending", nullable=True)  # 申请状态（pending, applied, interviewed, rejected, hired）
    application_time = Column(DateTime, server_default=func.now())  # 申请时间
    response_status = Column(String(50), default="no_response", nullable=True)  # 回复状态（no_response, replied, interviewed, rejected, hired）

    # 申请相关信息
    cover_letter = Column(Text, nullable=True)  # 求职信
    application_notes = Column(Text, nullable=True)  # 申请备注
    next_step_reminder = Column(Text, nullable=True)  # 下一步提醒

    # 自动化相关
    auto_apply = Column(String(10), default="false", nullable=True)  # 是否自动投递
    batch_id = Column(String(100), nullable=True)  # 批量投递ID
    automation_log = Column(Text, nullable=True)  # 自动化日志

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系
    user = relationship("User", backref="job_applications")
    seeker_profile = relationship("SeekerProfile", backref="job_applications")
    job_posting = relationship("JobPosting", backref="job_applications")
    resume = relationship("Resume", backref="job_applications")

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "seeker_profile_id": self.seeker_profile_id,
            "job_posting_id": self.job_posting_id,
            "resume_id": self.resume_id,
            "application_status": self.application_status,
            "application_time": self.application_time.isoformat() if self.application_time else None,
            "response_status": self.response_status,
            "cover_letter": self.cover_letter,
            "application_notes": self.application_notes,
            "next_step_reminder": self.next_step_reminder,
            "auto_apply": self.auto_apply,
            "batch_id": self.batch_id,
            "automation_log": self.automation_log,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }