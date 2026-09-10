from app.database import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

class JobPosting(Base):
    """职位表"""
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)  # 职位名称
    company = Column(String(255), nullable=False)  # 公司名称
    company_logo = Column(String(500), nullable=True)  # 公司Logo
    location = Column(String(255), nullable=True)  # 工作地点
    job_type = Column(String(50), nullable=True)  # 工作类型（全职、兼职、实习等）
    salary_range = Column(String(100), nullable=True)  # 薪资范围
    experience_required = Column(String(100), nullable=True)  # 工作经验要求
    education_required = Column(String(100), nullable=True)  # 学历要求
    industry = Column(String(100), nullable=True)  # 所属行业
    description = Column(Text, nullable=True)  # 职位描述
    requirements = Column(Text, nullable=True)  # 任职要求
    benefits = Column(Text, nullable=True)  # 福利待遇
    tags = Column(Text, nullable=True)  # 职位标签（JSON格式）
    source_url = Column(String(500), nullable=True)  # 源链接URL
    source_type = Column(String(50), nullable=True)  # 来源类型（智联、前程无忧等）
    source_id = Column(String(100), nullable=True)  # 来源ID
    application_url = Column(String(500), nullable=True)  # 申请链接
    application_deadline = Column(DateTime, nullable=True)  # 申请截止日期
    is_active = Column(String(10), default="true", nullable=True)  # 是否激活
    is_applied = Column(String(10), default="false", nullable=True)  # 是否已申请
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系
    job_applications = relationship("JobApplication", backref="job_posting")

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "company_logo": self.company_logo,
            "location": self.location,
            "job_type": self.job_type,
            "salary_range": self.salary_range,
            "experience_required": self.experience_required,
            "education_required": self.education_required,
            "industry": self.industry,
            "description": self.description,
            "requirements": self.requirements,
            "benefits": self.benefits,
            "tags": self.tags,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "application_url": self.application_url,
            "application_deadline": self.application_deadline.isoformat() if self.application_deadline else None,
            "is_active": self.is_active,
            "is_applied": self.is_applied,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }