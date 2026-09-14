from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, DateTime,
    Boolean, UniqueConstraint
)
from sqlalchemy.orm import relationship
from .database import Base


class University(Base):
    __tablename__ = "universities"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    country = Column(String, default="Kenya")
    courses = relationship("Course", back_populates="university")
    users = relationship("User", back_populates="university")


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False)
    title = Column(String, nullable=False)
    university_id = Column(Integer, ForeignKey("universities.id"))
    university = relationship("University", back_populates="courses")
    materials = relationship("Material", back_populates="course")
    enrollments = relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")
    groups = relationship("StudyGroup", back_populates="course")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    university_id = Column(Integer, ForeignKey("universities.id"), nullable=True)
    year_of_study = Column(Integer, default=1)
    is_admin = Column(Boolean, default=False)

    university = relationship("University", back_populates="users")
    materials = relationship("Material", back_populates="uploader")
    ratings = relationship("Rating", back_populates="user")
    events = relationship("InteractionEvent", back_populates="user")
    bookmarks = relationship("Bookmark", back_populates="user", cascade="all, delete-orphan")
    login_events = relationship("LoginEvent", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    study_notes = relationship("StudyNote", back_populates="user", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="user", cascade="all, delete-orphan")
    owned_groups = relationship("StudyGroup", back_populates="owner", cascade="all, delete-orphan")
    group_memberships = relationship("GroupMember", back_populates="user", cascade="all, delete-orphan")
    flags_reported = relationship("MaterialFlag", back_populates="reporter",
                                  foreign_keys="MaterialFlag.reporter_id")


class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    tags = Column(String, default="")
    kind = Column(String, default="notes")
    url = Column(String, default="")
    course_id = Column(Integer, ForeignKey("courses.id"))
    uploader_id = Column(Integer, ForeignKey("users.id"))
    hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    course = relationship("Course", back_populates="materials")
    uploader = relationship("User", back_populates="materials")
    ratings = relationship("Rating", back_populates="material", cascade="all, delete-orphan")
    events = relationship("InteractionEvent", back_populates="material", cascade="all, delete-orphan")
    bookmarks = relationship("Bookmark", back_populates="material", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="material", cascade="all, delete-orphan")
    study_notes = relationship("StudyNote", back_populates="material", cascade="all, delete-orphan")
    flags = relationship("MaterialFlag", back_populates="material", cascade="all, delete-orphan")

    @property
    def avg_rating(self):
        if not self.ratings:
            return 0.0
        return round(sum(r.score for r in self.ratings) / len(self.ratings), 2)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("user_id", "material_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))
    score = Column(Integer, default=0)
    user = relationship("User", back_populates="ratings")
    material = relationship("Material", back_populates="ratings")


class InteractionEvent(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))
    action = Column(String, default="view")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="events")
    material = relationship("Material", back_populates="events")


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "material_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    material_id = Column(Integer, ForeignKey("materials.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="bookmarks")
    material = relationship("Material", back_populates="bookmarks")


class LoginEvent(Base):
    __tablename__ = "login_events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="login_events")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materials.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="comments")
    material = relationship("Material", back_populates="comments")


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    kind = Column(String, default="info")
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="notifications")


# ---------------- Phase 6 ----------------

class StudyNote(Base):
    __tablename__ = "study_notes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), index=True)
    page = Column(Integer, nullable=True)   # optional page ref for PDFs
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="study_notes")
    material = relationship("Material", back_populates="study_notes")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")


class StudyGroup(Base):
    __tablename__ = "study_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner = relationship("User", back_populates="owned_groups")
    course = relationship("Course", back_populates="groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    shares = relationship("GroupShare", back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("study_groups.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    group = relationship("StudyGroup", back_populates="members")
    user = relationship("User", back_populates="group_memberships")


class GroupShare(Base):
    __tablename__ = "group_shares"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("study_groups.id"), index=True)
    material_id = Column(Integer, ForeignKey("materials.id"))
    shared_by = Column(Integer, ForeignKey("users.id"))
    note = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    group = relationship("StudyGroup", back_populates="shares")


class MaterialFlag(Base):
    __tablename__ = "material_flags"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materials.id"), index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"))
    reason = Column(String, default="other")
    details = Column(Text, default="")
    status = Column(String, default="pending")   # pending | dismissed | removed
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    material = relationship("Material", back_populates="flags")
    reporter = relationship("User", back_populates="flags_reported",
                            foreign_keys=[reporter_id])
    