from app.database import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

class Resume(Base):
    """简历表"""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False)
    file_path = Column(String(500), nullable=False)  # 文件存储路径
    file_name = Column(String(255), nullable=False)  # 原始文件名
    file_type = Column(String(50), nullable=True)  # 文件类型 (pdf, docx, txt)
    file_size = Column(Integer, nullable=True)  # 文件大小（字节）
    extracted_text = Column(Text, nullable=True)  # 提取的文本内容
    extracted_skills = Column(Text, nullable=True)  # 提取的技能（JSON格式）
    work_experience = Column(Text, nullable=True)  # 工作经历（解析后的JSON）
    education = Column(Text, nullable=True)  # 教育背景（解析后的JSON）
    projects = Column(Text, nullable=True)  # 项目经验（JSON格式）
    certifications = Column(Text, nullable=True)  # 证书（JSON格式）
    languages = Column(Text, nullable=True)  # 语言能力（JSON格式）
    self_description = Column(Text, nullable=True)  # 自我评价
    status = Column(String(50), default="active", nullable=True)  # 简历状态
    is_default = Column(String(10), default="false", nullable=True)  # 是否为默认简历
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系
    user = relationship("User", backref="resumes")
    seeker_profile = relationship("SeekerProfile", backref="resumes")
    job_applications = relationship("JobApplication", backref="resume")

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "seeker_profile_id": self.seeker_profile_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "extracted_text": self.extracted_text,
            "extracted_skills": self.extracted_skills,
            "work_experience": self.work_experience,
            "education": self.education,
            "projects": self.projects,
            "certifications": self.certifications,
            "languages": self.languages,
            "self_description": self.self_description,
            "status": self.status,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }