"""StudyHub API — Phase 6."""
import os
import atexit
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    FastAPI, Depends, HTTPException, Query,
    UploadFile, File, Form, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt, JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, SessionLocal
from . import models, schemas, auth, recommender, uploads
from .realtime import manager


Base.metadata.create_all(bind=engine)
Path("uploads").mkdir(exist_ok=True)

app = FastAPI(title="StudyHub API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ==================================================================
# HELPERS
# ==================================================================
def _calc_streak(db: Session, user_id: int) -> tuple[int, int]:
    rows = db.query(models.LoginEvent.created_at).filter(
        models.LoginEvent.user_id == user_id).all()
    date_set = {r[0].date() for r in rows if r[0]}
    if not date_set:
        return 0, 0
    today = datetime.now(timezone.utc).date()
    current, expected = 0, today
    for d in sorted(date_set, reverse=True):
        if d == expected:
            current += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    longest = run = 0
    prev = None
    for d in sorted(date_set):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    return current, longest


def _material_summary(m: models.Material) -> dict:
    return {"id": m.id, "title": m.title, "kind": m.kind,
            "course_id": m.course_id, "url": m.url, "tags": m.tags or ""}


def _notify(db, user_id, kind, title, body="", material_id=None):
    if not user_id:
        return
    db.add(models.Notification(user_id=user_id, kind=kind, title=title,
                               body=body, material_id=material_id))


def _require_admin(user: models.User):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")


# ==================================================================
# AUTH
# ==================================================================
@app.post("/api/auth/register", response_model=schemas.UserOut, tags=["auth"])
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    user = models.User(
        name=payload.name, email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        university_id=payload.university_id,
        year_of_study=payload.year_of_study,
    )
    db.add(user); db.commit(); db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=schemas.Token, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form.username).first()
    if not user or not auth.verify_password(form.password, user.hashed_password):
        raise HTTPException(401, "Incorrect email or password")
    db.add(models.LoginEvent(user_id=user.id)); db.commit()
    return {"access_token": auth.create_access_token(user.id)}


@app.get("/api/auth/me", response_model=schemas.UserOut, tags=["auth"])
def me(user: models.User = Depends(auth.get_current_user)):
    return user


# ==================================================================
# ME
# ==================================================================
@app.post("/api/me/touch", tags=["me"])
def touch(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    existing = db.query(models.LoginEvent).filter(
        models.LoginEvent.user_id == user.id,
        models.LoginEvent.created_at >= today_start).first()
    if not existing:
        db.add(models.LoginEvent(user_id=user.id)); db.commit()
    return {"ok": True}


@app.get("/api/me/profile", response_model=schemas.UserProfile, tags=["me"])
def my_profile(db: Session = Depends(get_db),
               user: models.User = Depends(auth.get_current_user)):
    current, longest = _calc_streak(db, user.id)
    first = (db.query(models.LoginEvent)
             .filter_by(user_id=user.id)
             .order_by(models.LoginEvent.created_at.asc()).first())
    joined_days_ago = 0
    if first and first.created_at:
        joined_days_ago = max(0, (datetime.now(timezone.utc).date()
                                  - first.created_at.date()).days)
    return schemas.UserProfile(
        user=user,
        streak_current=current, streak_longest=longest,
        total_bookmarks=db.query(models.Bookmark).filter_by(user_id=user.id).count(),
        total_downloads=db.query(models.InteractionEvent).filter_by(
            user_id=user.id, action="download").count(),
        total_ratings=db.query(models.Rating).filter_by(user_id=user.id).count(),
        total_events=db.query(models.InteractionEvent).filter_by(user_id=user.id).count(),
        total_uploads=db.query(models.Material).filter_by(uploader_id=user.id).count(),
        total_notes=db.query(models.StudyNote).filter_by(user_id=user.id).count(),
        joined_days_ago=joined_days_ago,
    )


# ==================================================================
# CATALOG
# ==================================================================
@app.get("/api/universities", response_model=list[schemas.UniversityOut], tags=["catalog"])
def list_universities(db: Session = Depends(get_db)):
    return db.query(models.University).all()


@app.get("/api/courses", response_model=list[schemas.CourseOut], tags=["catalog"])
def list_courses(university_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Course)
    if university_id:
        q = q.filter(models.Course.university_id == university_id)
    return q.all()


@app.get("/api/courses/{course_id}/materials",
         response_model=list[schemas.MaterialOut], tags=["catalog"])
def course_materials(course_id: int, db: Session = Depends(get_db)):
    if not db.get(models.Course, course_id):
        raise HTTPException(404, "Course not found")
    return (db.query(models.Material)
            .filter(models.Material.course_id == course_id,
                    models.Material.hidden == False)
            .order_by(models.Material.created_at.desc()).all())


# ==================================================================
# MATERIALS
# ==================================================================
@app.post("/api/materials", response_model=schemas.MaterialOut, tags=["materials"])
async def create_material(payload: schemas.MaterialCreate,
                          db: Session = Depends(get_db),
                          user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.Course, payload.course_id):
        raise HTTPException(404, "Course not found")
    material = models.Material(**payload.model_dump(), uploader_id=user.id)
    db.add(material); db.commit(); db.refresh(material)
    recommender.build_index(db)
    await manager.broadcast({"type": "material_created",
                             "material": _material_summary(material)})
    return material


@app.post("/api/materials/upload", response_model=schemas.MaterialOut, tags=["materials"])
async def upload_material(
    title: str = Form(...), course_id: int = Form(...),
    kind: str = Form("notes"), description: str = Form(""),
    tags: str = Form(""), file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if not db.get(models.Course, course_id):
        raise HTTPException(404, "Course not found")
    try:
        url = uploads.save_file(file)
    except ValueError as e:
        raise HTTPException(400, str(e))

    local_path = Path(".") / url.lstrip("/")
    extracted = uploads.extract_text(local_path)
    auto = uploads.auto_tags(extracted, title)
    combined_tags = ", ".join(filter(None, [tags.strip(), auto])).strip(", ")
    combined_desc = (description + ("\n\n" + extracted[:800] if extracted else "")).strip()

    material = models.Material(
        title=title, description=combined_desc, tags=combined_tags,
        kind=kind, url=url, course_id=course_id, uploader_id=user.id,
    )
    db.add(material); db.commit(); db.refresh(material)
    recommender.build_index(db)

    if user.university_id:
        peers = (db.query(models.User)
                 .filter(models.User.university_id == user.university_id,
                         models.User.id != user.id).all())
        for p in peers:
            _notify(db, p.id, "new_material",
                    f"New {kind} in {material.course.code if material.course else 'your courses'}",
                    material.title, material.id)
        db.commit()

    await manager.broadcast({"type": "material_created",
                             "material": _material_summary(material)})
    return material


@app.get("/api/materials/search", response_model=list[schemas.MaterialOut], tags=["materials"])
def search_materials(
    q: str = Query("", min_length=0),
    course_id: int | None = None,
    kind: str | None = None,
    min_rating: float | None = None,
    days: int | None = None,
    sort: str = Query("recent", pattern="^(recent|rating|popular)$"),
    db: Session = Depends(get_db),
):
    query = db.query(models.Material).filter(models.Material.hidden == False)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            models.Material.title.ilike(like)
            | models.Material.description.ilike(like)
            | models.Material.tags.ilike(like))
    if course_id:
        query = query.filter(models.Material.course_id == course_id)
    if kind:
        query = query.filter(models.Material.kind == kind)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(models.Material.created_at >= cutoff)

    results = query.all()
    if min_rating is not None:
        results = [m for m in results if m.avg_rating >= min_rating]

    if sort == "rating":
        results.sort(key=lambda m: m.avg_rating, reverse=True)
    elif sort == "popular":
        results.sort(key=lambda m: sum(1 for e in m.events if e.action == "download"),
                     reverse=True)
    else:
        results.sort(key=lambda m: m.created_at or datetime.min, reverse=True)
    return results


@app.get("/api/materials/{material_id}", response_model=schemas.MaterialOut, tags=["materials"])
def get_material(material_id: int, db: Session = Depends(get_db)):
    m = db.get(models.Material, material_id)
    if not m:
        raise HTTPException(404, "Material not found")
    return m


# ==================================================================
# RECOMMENDATIONS
# ==================================================================
@app.get("/api/recommendations/me",
         response_model=list[schemas.MaterialRecommendation], tags=["ai"])
def my_recommendations(limit: int = 10, db: Session = Depends(get_db),
                       user: models.User = Depends(auth.get_current_user)):
    ranked = recommender.recommend_for_user(db, user, limit=limit)
    out = []
    for r in ranked:
        m = r["material"]
        if m.hidden:
            continue
        out.append(schemas.MaterialRecommendation(
            id=m.id, title=m.title, description=m.description, tags=m.tags,
            kind=m.kind, url=m.url, course_id=m.course_id, hidden=m.hidden,
            avg_rating=m.avg_rating, created_at=m.created_at,
            score=r["score"], reason=r["reason"]))
    return out


# ==================================================================
# ENGAGEMENT
# ==================================================================
@app.post("/api/materials/{material_id}/rate", tags=["engagement"])
def rate_material(material_id: int, payload: schemas.RatingIn,
                  db: Session = Depends(get_db),
                  user: models.User = Depends(auth.get_current_user)):
    if not 1 <= payload.score <= 5:
        raise HTTPException(400, "Score must be 1-5")
    m = db.get(models.Material, material_id)
    if not m:
        raise HTTPException(404, "Material not found")
    existing = db.query(models.Rating).filter_by(
        user_id=user.id, material_id=material_id).first()
    if existing:
        existing.score = payload.score
    else:
        db.add(models.Rating(user_id=user.id, material_id=material_id,
                             score=payload.score))
    if m.uploader_id and m.uploader_id != user.id:
        _notify(db, m.uploader_id, "comment",
                f"{user.name} rated your material {payload.score}/5",
                m.title, m.id)
    db.commit()
    return {"ok": True}


@app.post("/api/materials/{material_id}/event", tags=["engagement"])
def log_event(material_id: int,
              action: str = Query("view", pattern="^(view|download|save)$"),
              db: Session = Depends(get_db),
              user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.Material, material_id):
        raise HTTPException(404, "Material not found")
    db.add(models.InteractionEvent(user_id=user.id,
                                   material_id=material_id, action=action))
    db.commit()
    return {"ok": True}


# ==================================================================
# BOOKMARKS
# ==================================================================
@app.get("/api/bookmarks", response_model=list[schemas.BookmarkOut], tags=["bookmarks"])
def list_bookmarks(db: Session = Depends(get_db),
                   user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.Bookmark).filter_by(user_id=user.id)
            .order_by(models.Bookmark.created_at.desc()).all())


@app.post("/api/materials/{material_id}/bookmark", tags=["bookmarks"])
def add_bookmark(material_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.Material, material_id):
        raise HTTPException(404, "Material not found")
    if not db.query(models.Bookmark).filter_by(
            user_id=user.id, material_id=material_id).first():
        db.add(models.Bookmark(user_id=user.id, material_id=material_id))
        db.commit()
    return {"ok": True, "bookmarked": True}


@app.delete("/api/materials/{material_id}/bookmark", tags=["bookmarks"])
def remove_bookmark(material_id: int, db: Session = Depends(get_db),
                    user: models.User = Depends(auth.get_current_user)):
    bm = db.query(models.Bookmark).filter_by(
        user_id=user.id, material_id=material_id).first()
    if bm:
        db.delete(bm); db.commit()
    return {"ok": True, "bookmarked": False}


# ==================================================================
# COMMENTS
# ==================================================================
@app.get("/api/materials/{material_id}/comments",
         response_model=list[schemas.CommentOut], tags=["comments"])
def list_comments(material_id: int, db: Session = Depends(get_db)):
    return (db.query(models.Comment).filter_by(material_id=material_id)
            .order_by(models.Comment.created_at.asc()).all())


@app.post("/api/materials/{material_id}/comments",
          response_model=schemas.CommentOut, tags=["comments"])
async def add_comment(material_id: int, payload: schemas.CommentCreate,
                      db: Session = Depends(get_db),
                      user: models.User = Depends(auth.get_current_user)):
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Comment cannot be empty")
    m = db.get(models.Material, material_id)
    if not m:
        raise HTTPException(404, "Material not found")
    c = models.Comment(material_id=material_id, user_id=user.id, body=body[:2000])
    db.add(c)
    if m.uploader_id and m.uploader_id != user.id:
        _notify(db, m.uploader_id, "comment",
                f"{user.name} commented on your material",
                body[:120], m.id)
    db.commit(); db.refresh(c)
    await manager.broadcast({"type": "comment_created",
                             "material_id": material_id})
    return c


@app.delete("/api/comments/{comment_id}", tags=["comments"])
def delete_comment(comment_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(auth.get_current_user)):
    c = db.get(models.Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    if c.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "Not your comment")
    db.delete(c); db.commit()
    return {"ok": True}


# ==================================================================
# NOTIFICATIONS
# ==================================================================
@app.get("/api/notifications", response_model=list[schemas.NotificationOut],
         tags=["notifications"])
def list_notifications(limit: int = 30, db: Session = Depends(get_db),
                       user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.Notification).filter_by(user_id=user.id)
            .order_by(models.Notification.created_at.desc()).limit(limit).all())


@app.post("/api/notifications/read-all", tags=["notifications"])
def read_all(db: Session = Depends(get_db),
             user: models.User = Depends(auth.get_current_user)):
    db.query(models.Notification).filter_by(user_id=user.id, read=False)\
      .update({"read": True})
    db.commit()
    return {"ok": True}


@app.post("/api/notifications/{notification_id}/read", tags=["notifications"])
def read_one(notification_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(auth.get_current_user)):
    n = db.get(models.Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Not found")
    n.read = True
    db.commit()
    return {"ok": True}


# ==================================================================
# LEADERBOARD (fixed)
# ==================================================================
@app.get("/api/leaderboard", response_model=list[schemas.LeaderboardRow], tags=["leaderboard"])
def leaderboard(limit: int = 20, db: Session = Depends(get_db)):
    rows = []
    users = db.query(models.User).all()
    for u in users:
        uploads = db.query(models.Material).filter_by(uploader_id=u.id).count()
        downloads = (db.query(models.InteractionEvent)
                     .filter_by(user_id=u.id, action="download").count())

        # Average rating across THIS user's uploaded materials
        user_mats = db.query(models.Material).filter_by(uploader_id=u.id).all()
        ratings = (sum(m.avg_rating for m in user_mats) / len(user_mats)) if user_mats else 0.0

        score = uploads * 5 + downloads * 1 + ratings * 2
        if score == 0:
            continue
        rows.append(schemas.LeaderboardRow(
            user_id=u.id, name=u.name, uploads=uploads,
            downloads=downloads, avg_rating=round(ratings, 2),
            score=round(score, 2)))
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows[:limit]


# ==================================================================
# STUDY SESSIONS
# ==================================================================
@app.post("/api/me/study-session", tags=["me"])
def log_study_session(payload: schemas.StudySessionIn,
                      db: Session = Depends(get_db),
                      user: models.User = Depends(auth.get_current_user)):
    if payload.minutes < 1 or payload.minutes > 240:
        raise HTTPException(400, "Minutes must be 1-240")
    db.add(models.InteractionEvent(
        user_id=user.id, material_id=payload.material_id or 1, action="save"))
    db.commit()
    return {"ok": True}


# ==================================================================
# STUDY NOTES
# ==================================================================
@app.get("/api/materials/{material_id}/notes",
         response_model=list[schemas.StudyNoteOut], tags=["notes"])
def list_notes(material_id: int, db: Session = Depends(get_db),
               user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.StudyNote)
            .filter_by(user_id=user.id, material_id=material_id)
            .order_by(models.StudyNote.page.asc().nullsfirst(),
                      models.StudyNote.created_at.asc()).all())


@app.get("/api/me/notes", response_model=list[schemas.StudyNoteOut], tags=["notes"])
def my_notes(db: Session = Depends(get_db),
             user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.StudyNote).filter_by(user_id=user.id)
            .order_by(models.StudyNote.updated_at.desc()).all())


@app.post("/api/materials/{material_id}/notes",
          response_model=schemas.StudyNoteOut, tags=["notes"])
def add_note(material_id: int, payload: schemas.StudyNoteCreate,
             db: Session = Depends(get_db),
             user: models.User = Depends(auth.get_current_user)):
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Note body required")
    if not db.get(models.Material, material_id):
        raise HTTPException(404, "Material not found")
    n = models.StudyNote(user_id=user.id, material_id=material_id,
                         page=payload.page, body=body[:5000])
    db.add(n); db.commit(); db.refresh(n)
    return n


@app.patch("/api/notes/{note_id}", response_model=schemas.StudyNoteOut, tags=["notes"])
def update_note(note_id: int, payload: schemas.StudyNoteUpdate,
                db: Session = Depends(get_db),
                user: models.User = Depends(auth.get_current_user)):
    n = db.get(models.StudyNote, note_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Note not found")
    if payload.body is not None:
        n.body = payload.body.strip()[:5000]
    if payload.page is not None:
        n.page = payload.page
    db.commit(); db.refresh(n)
    return n


@app.delete("/api/notes/{note_id}", tags=["notes"])
def delete_note(note_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(auth.get_current_user)):
    n = db.get(models.StudyNote, note_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Note not found")
    db.delete(n); db.commit()
    return {"ok": True}


# ==================================================================
# ENROLLMENT
# ==================================================================
@app.get("/api/me/enrollments", response_model=list[schemas.EnrollmentOut], tags=["enrollment"])
def my_enrollments(db: Session = Depends(get_db),
                   user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.Enrollment).filter_by(user_id=user.id)
            .order_by(models.Enrollment.created_at.desc()).all())


@app.post("/api/courses/{course_id}/enroll", tags=["enrollment"])
def enroll(course_id: int, db: Session = Depends(get_db),
           user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.Course, course_id):
        raise HTTPException(404, "Course not found")
    if not db.query(models.Enrollment).filter_by(
            user_id=user.id, course_id=course_id).first():
        db.add(models.Enrollment(user_id=user.id, course_id=course_id))
        db.commit()
    return {"ok": True, "enrolled": True}


@app.delete("/api/courses/{course_id}/enroll", tags=["enrollment"])
def unenroll(course_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(auth.get_current_user)):
    e = db.query(models.Enrollment).filter_by(
        user_id=user.id, course_id=course_id).first()
    if e:
        db.delete(e); db.commit()
    return {"ok": True, "enrolled": False}


# ==================================================================
# STUDY GROUPS
# ==================================================================
@app.get("/api/groups", response_model=list[schemas.StudyGroupOut], tags=["groups"])
def list_groups(mine: bool = False, course_id: int | None = None,
                db: Session = Depends(get_db),
                user: models.User = Depends(auth.get_current_user)):
    q = db.query(models.StudyGroup)
    if course_id:
        q = q.filter(models.StudyGroup.course_id == course_id)
    groups = q.order_by(models.StudyGroup.created_at.desc()).all()

    my_group_ids = {gm.group_id for gm in db.query(models.GroupMember)
                    .filter_by(user_id=user.id).all()}
    if mine:
        groups = [g for g in groups if g.id in my_group_ids]

    out = []
    for g in groups:
        member_count = db.query(models.GroupMember).filter_by(group_id=g.id).count()
        out.append(schemas.StudyGroupOut(
            id=g.id, name=g.name, description=g.description,
            course_id=g.course_id, owner_id=g.owner_id,
            created_at=g.created_at, member_count=member_count,
            is_member=g.id in my_group_ids))
    return out


@app.post("/api/groups", response_model=schemas.StudyGroupOut, tags=["groups"])
def create_group(payload: schemas.StudyGroupCreate,
                 db: Session = Depends(get_db),
                 user: models.User = Depends(auth.get_current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Group name required")
    if payload.course_id and not db.get(models.Course, payload.course_id):
        raise HTTPException(404, "Course not found")
    g = models.StudyGroup(name=name[:120], description=payload.description[:500],
                          course_id=payload.course_id, owner_id=user.id)
    db.add(g); db.commit(); db.refresh(g)
    db.add(models.GroupMember(group_id=g.id, user_id=user.id))
    db.commit()
    return schemas.StudyGroupOut(
        id=g.id, name=g.name, description=g.description,
        course_id=g.course_id, owner_id=g.owner_id,
        created_at=g.created_at, member_count=1, is_member=True)


@app.get("/api/groups/{group_id}", response_model=schemas.StudyGroupOut, tags=["groups"])
def get_group(group_id: int, db: Session = Depends(get_db),
              user: models.User = Depends(auth.get_current_user)):
    g = db.get(models.StudyGroup, group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    is_member = bool(db.query(models.GroupMember).filter_by(
        group_id=group_id, user_id=user.id).first())
    count = db.query(models.GroupMember).filter_by(group_id=group_id).count()
    return schemas.StudyGroupOut(
        id=g.id, name=g.name, description=g.description,
        course_id=g.course_id, owner_id=g.owner_id,
        created_at=g.created_at, member_count=count, is_member=is_member)


@app.post("/api/groups/{group_id}/join", tags=["groups"])
def join_group(group_id: int, db: Session = Depends(get_db),
               user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.StudyGroup, group_id):
        raise HTTPException(404, "Group not found")
    if not db.query(models.GroupMember).filter_by(
            group_id=group_id, user_id=user.id).first():
        db.add(models.GroupMember(group_id=group_id, user_id=user.id))
        db.commit()
    return {"ok": True}


@app.delete("/api/groups/{group_id}/leave", tags=["groups"])
def leave_group(group_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(auth.get_current_user)):
    gm = db.query(models.GroupMember).filter_by(
        group_id=group_id, user_id=user.id).first()
    if gm:
        db.delete(gm); db.commit()
    return {"ok": True}


@app.get("/api/groups/{group_id}/members",
         response_model=list[schemas.GroupMemberOut], tags=["groups"])
def group_members(group_id: int, db: Session = Depends(get_db)):
    return (db.query(models.GroupMember).filter_by(group_id=group_id)
            .order_by(models.GroupMember.joined_at.asc()).all())


@app.get("/api/groups/{group_id}/shares",
         response_model=list[schemas.GroupShareOut], tags=["groups"])
def group_shares(group_id: int, db: Session = Depends(get_db)):
    return (db.query(models.GroupShare).filter_by(group_id=group_id)
            .order_by(models.GroupShare.created_at.desc()).all())


@app.post("/api/groups/{group_id}/share", response_model=schemas.GroupShareOut,
          tags=["groups"])
async def share_to_group(group_id: int, payload: schemas.GroupShareCreate,
                         db: Session = Depends(get_db),
                         user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.StudyGroup, group_id):
        raise HTTPException(404, "Group not found")
    if not db.query(models.GroupMember).filter_by(
            group_id=group_id, user_id=user.id).first():
        raise HTTPException(403, "Join the group first")
    if not db.get(models.Material, payload.material_id):
        raise HTTPException(404, "Material not found")

    s = models.GroupShare(group_id=group_id, material_id=payload.material_id,
                          shared_by=user.id, note=payload.note[:300])
    db.add(s); db.commit(); db.refresh(s)

    members = db.query(models.GroupMember).filter_by(group_id=group_id).all()
    g = db.get(models.StudyGroup, group_id)
    for m in members:
        if m.user_id != user.id:
            _notify(db, m.user_id, "info",
                    f"{user.name} shared a material in {g.name}",
                    s.material.title if s.material else "", payload.material_id)
    db.commit()
    return s


# ==================================================================
# MODERATION
# ==================================================================
@app.post("/api/materials/{material_id}/flag", tags=["moderation"])
def flag_material(material_id: int, payload: schemas.FlagCreate,
                  db: Session = Depends(get_db),
                  user: models.User = Depends(auth.get_current_user)):
    if not db.get(models.Material, material_id):
        raise HTTPException(404, "Material not found")
    f = models.MaterialFlag(
        material_id=material_id, reporter_id=user.id,
        reason=payload.reason[:60], details=payload.details[:500])
    db.add(f); db.commit()
    admins = db.query(models.User).filter_by(is_admin=True).all()
    for a in admins:
        _notify(db, a.id, "info", "New flag submitted",
                f"{payload.reason} on material #{material_id}", material_id)
    db.commit()
    return {"ok": True}


@app.get("/api/admin/flags", response_model=list[schemas.FlagOut], tags=["moderation"])
def admin_flags(status: str = Query("pending",
                                    pattern="^(pending|dismissed|removed|all)$"),
                db: Session = Depends(get_db),
                user: models.User = Depends(auth.get_current_user)):
    _require_admin(user)
    q = db.query(models.MaterialFlag)
    if status != "all":
        q = q.filter(models.MaterialFlag.status == status)
    return q.order_by(models.MaterialFlag.created_at.desc()).all()


@app.post("/api/admin/flags/{flag_id}/dismiss", tags=["moderation"])
def dismiss_flag(flag_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(auth.get_current_user)):
    _require_admin(user)
    f = db.get(models.MaterialFlag, flag_id)
    if not f:
        raise HTTPException(404, "Flag not found")
    f.status = "dismissed"
    f.reviewed_by = user.id
    f.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/flags/{flag_id}/remove-material", tags=["moderation"])
def remove_material_via_flag(flag_id: int, db: Session = Depends(get_db),
                             user: models.User = Depends(auth.get_current_user)):
    _require_admin(user)
    f = db.get(models.MaterialFlag, flag_id)
    if not f:
        raise HTTPException(404, "Flag not found")
    f.status = "removed"
    f.reviewed_by = user.id
    f.reviewed_at = datetime.now(timezone.utc)
    m = db.get(models.Material, f.material_id)
    if m:
        m.hidden = True
        if m.uploader_id:
            _notify(db, m.uploader_id, "info",
                    "Your material was hidden after moderation review",
                    m.title, m.id)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/materials/{material_id}/restore", tags=["moderation"])
def restore_material(material_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(auth.get_current_user)):
    _require_admin(user)
    m = db.get(models.Material, material_id)
    if not m:
        raise HTTPException(404, "Material not found")
    m.hidden = False
    db.commit()
    return {"ok": True}


# ==================================================================
# ADMIN STATS
# ==================================================================
@app.get("/api/admin/stats", tags=["admin"])
def stats(db: Session = Depends(get_db)):
    return {
        "users": db.query(models.User).count(),
        "materials": db.query(models.Material).count(),
        "hidden_materials": db.query(models.Material).filter_by(hidden=True).count(),
        "events": db.query(models.InteractionEvent).count(),
        "ratings": db.query(models.Rating).count(),
        "bookmarks": db.query(models.Bookmark).count(),
        "comments": db.query(models.Comment).count(),
        "notes": db.query(models.StudyNote).count(),
        "enrollments": db.query(models.Enrollment).count(),
        "groups": db.query(models.StudyGroup).count(),
        "pending_flags": db.query(models.MaterialFlag).filter_by(status="pending").count(),
        "using_embeddings": recommender.is_using_embeddings(),
        "live_connections": manager.count,
        "top_actions": dict(db.query(models.InteractionEvent.action, func.count())
                            .group_by(models.InteractionEvent.action).all()),
    }


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "studyhub"}


# ==================================================================
# WEBSOCKET
# ==================================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008); return
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        await websocket.close(code=1008); return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ==================================================================
# SHARE LINK
# ==================================================================
@app.get("/material/{material_id}", response_class=HTMLResponse, include_in_schema=False)
def material_share(material_id: int, db: Session = Depends(get_db)):
    m = db.get(models.Material, material_id)
    if not m:
        return RedirectResponse(url="/")
    title = (m.title or "Study material").replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta property="og:title" content="{title}">
<style>body{{font-family:system-ui;background:#0a0b0f;color:#eef0f4;padding:40px;text-align:center}}
a{{color:#4ade80}}</style></head><body>
<h2>{title}</h2><p>Opening StudyHub…</p>
<script>setTimeout(()=>location.href="/#/material/{material_id}",400)</script>
</body></html>"""


# ==================================================================
# SCHEDULER
# ==================================================================
if os.environ.get("STUDYHUB_DISABLE_SCHEDULER") != "1":
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        def _retrain():
            db = SessionLocal()
            try: recommender.build_index(db)
            except Exception as e: print(f"[retrain] failed: {e}")
            finally: db.close()
        _s = BackgroundScheduler(daemon=True)
        _s.add_job(_retrain, "interval", hours=6, id="retrain", replace_existing=True)
        _s.start()
        atexit.register(lambda: _s.shutdown(wait=False))
        print("[scheduler] recommender retrain scheduled every 6h")
    except ImportError:
        print("[scheduler] apscheduler not installed — skipping periodic retrain")


# ==================================================================
# STATIC
# ==================================================================
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


import subprocess
from fastapi import Query
import os


@app.get("/api/admin/seed-database", tags=["admin"])
def seed_database(
    key: str = Query(...), # This makes the "key" parameter required
    user: models.User = Depends(auth.get_current_user)
):
    """
    TEMPORARY ENDPOINT: Run the database seeding script.
    Protected by a secret key and admin login.
    """
    _require_admin(user)
    
    # Set a secret key in your Render environment variables
    expected_key = os.getenv("SEED_SECRET_KEY")
    if not expected_key or key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid seed key.")
        
    try:
        # Run the seed script as a subprocess
        result = subprocess.run(
            [sys.executable, "run_seed.py"],
            capture_output=True,
            text=True,
            check=True
        )
        return {"ok": True, "message": "Seeding successful!", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "message": "Seeding failed!", "output": e.stderr}
    