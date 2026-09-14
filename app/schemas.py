from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, ConfigDict


# ---------- Auth ----------
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    university_id: Optional[int] = None
    year_of_study: int = 1


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    university_id: Optional[int]
    year_of_study: int
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Catalog ----------
class UniversityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    country: str


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    title: str
    university_id: int


# ---------- Materials ----------
class MaterialCreate(BaseModel):
    title: str
    description: str = ""
    tags: str = ""
    kind: str = "notes"
    url: str = ""
    course_id: int


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    tags: str
    kind: str
    url: str
    course_id: int
    hidden: bool = False
    avg_rating: float
    created_at: datetime


class MaterialRecommendation(MaterialOut):
    score: float
    reason: str


class RatingIn(BaseModel):
    score: int


class BookmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    created_at: datetime
    material: MaterialOut


# ---------- Profile ----------
class UserProfile(BaseModel):
    user: UserOut
    streak_current: int
    streak_longest: int
    total_bookmarks: int
    total_downloads: int
    total_ratings: int
    total_events: int
    total_uploads: int
    total_notes: int
    joined_days_ago: int


# ---------- Comments ----------
class CommentCreate(BaseModel):
    body: str


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    user_id: int
    body: str
    created_at: datetime
    user: UserOut


# ---------- Notifications ----------
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    body: str
    material_id: Optional[int]
    read: bool
    created_at: datetime


# ---------- Leaderboard ----------
class LeaderboardRow(BaseModel):
    user_id: int
    name: str
    uploads: int
    downloads: int
    avg_rating: float
    score: float


# ---------- Study Sessions ----------
class StudySessionIn(BaseModel):
    minutes: int
    material_id: Optional[int] = None


# ---------- Study Notes ----------
class StudyNoteCreate(BaseModel):
    body: str
    page: Optional[int] = None


class StudyNoteUpdate(BaseModel):
    body: Optional[str] = None
    page: Optional[int] = None


class StudyNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    user_id: int
    page: Optional[int]
    body: str
    created_at: datetime
    updated_at: datetime


# ---------- Enrollment ----------
class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    created_at: datetime
    course: CourseOut


# ---------- Study Groups ----------
class StudyGroupCreate(BaseModel):
    name: str
    description: str = ""
    course_id: Optional[int] = None


class StudyGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    course_id: Optional[int]
    owner_id: int
    created_at: datetime
    member_count: int = 0
    is_member: bool = False


class GroupMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    joined_at: datetime
    user: UserOut


class GroupShareCreate(BaseModel):
    material_id: int
    note: str = ""


class GroupShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    material_id: int
    shared_by: int
    note: str
    created_at: datetime
    material: MaterialOut


# ---------- Moderation ----------
class FlagCreate(BaseModel):
    reason: str = "other"
    details: str = ""


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    reporter_id: int
    reason: str
    details: str
    status: str
    created_at: datetime
    material: MaterialOut
    