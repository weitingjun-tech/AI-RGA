from app.database import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

class SeekerProfile(Base):
    """求职者档案表"""
    __tablename__ = "seeker_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    location = Column(String(255), nullable=True)
    education = Column(Text, nullable=True)  # 教育经历 JSON 格式
    work_experience = Column(Text, nullable=True)  # 工作经历 JSON 格式
    skills = Column(Text, nullable=True)  # 技能列表 JSON 格式
    expected_job_type = Column(String(100), nullable=True)  # 期望职位类型
    expected_salary = Column(String(50), nullable=True)  # 期望薪资
    resume_summary = Column(Text, nullable=True)  # 个人简介
    avatar_url = Column(String(500), nullable=True)  # 头像URL
    status = Column(String(50), default="active", nullable=True)  # 档案状态
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系
    user = relationship("User", backref="seeker_profile")
    resumes = relationship("Resume", backref="seeker_profile", cascade="all, delete-orphan")

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "location": self.location,
            "education": self.education,
            "work_experience": self.work_experience,
            "skills": self.skills,
            "expected_job_type": self.expected_job_type,
            "expected_salary": self.expected_salary,
            "resume_summary": self.resume_summary,
            "avatar_url": self.avatar_url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }