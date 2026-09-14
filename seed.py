import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import Base, engine, SessionLocal
from app import models, auth, recommender

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if db.query(models.University).count() == 0:
    u1 = models.University(name="University of Nairobi", country="Kenya")
    u2 = models.University(name="Makerere University", country="Uganda")
    db.add_all([u1, u2])
    db.commit()

    courses = [
        models.Course(code="CSC301", title="Data Structures & Algorithms",
                      university_id=u1.id),
        models.Course(code="CSC402", title="Machine Learning", university_id=u1.id),
        models.Course(code="MAT201", title="Linear Algebra", university_id=u1.id),
        models.Course(code="STA210", title="Probability & Statistics",
                      university_id=u1.id),
        models.Course(code="CSC310", title="Operating Systems", university_id=u1.id),
    ]
    db.add_all(courses)
    db.commit()

    demo = models.User(
        name="Demo Student", email="demo@studyhub.ai",
        hashed_password=auth.hash_password("demo1234"),
        university_id=u1.id, year_of_study=3,
        is_admin=True,
    )
    db.add(demo)
    db.commit()

    # Auto-enroll the demo user in a few courses
    for code in ["CSC301", "CSC402", "MAT201"]:
        c = next((x for x in courses if x.code == code), None)
        if c:
            db.add(models.Enrollment(user_id=demo.id, course_id=c.id))
    db.commit()

    c = {x.code: x.id for x in courses}
    materials = [
        models.Material(title="CSC301 Past Paper 2023",
                        description="End of semester exam with marking scheme.",
                        tags="algorithms, past paper, exams, trees, graphs",
                        kind="past_paper", url="https://example.com/csc301-2023.pdf",
                        course_id=c["CSC301"], uploader_id=demo.id),
        models.Material(title="Big-O Cheat Sheet",
                        description="Time and space complexity for common algorithms.",
                        tags="algorithms, complexity, big-o, revision",
                        kind="notes", url="https://example.com/bigo.pdf",
                        course_id=c["CSC301"], uploader_id=demo.id),
        models.Material(title="Intro to Supervised Learning",
                        description="Linear regression, logistic regression, and trees.",
                        tags="machine learning, regression, classification",
                        kind="slides", url="https://example.com/ml-intro.pdf",
                        course_id=c["CSC402"], uploader_id=demo.id),
        models.Material(title="Neural Networks Explained Simply",
                        description="Backpropagation and gradient descent from scratch.",
                        tags="machine learning, neural networks, deep learning",
                        kind="video", url="https://example.com/nn.mp4",
                        course_id=c["CSC402"], uploader_id=demo.id),
        models.Material(title="Eigenvalues & Eigenvectors Drill Set",
                        description="50 practice problems with full solutions.",
                        tags="linear algebra, eigenvalues, matrices, practice",
                        kind="notes", url="https://example.com/eigen.pdf",
                        course_id=c["MAT201"], uploader_id=demo.id),
        models.Material(title="Probability Distributions Summary",
                        description="Binomial, Poisson, Normal — formulas and examples.",
                        tags="statistics, probability, distributions",
                        kind="notes", url="https://example.com/dist.pdf",
                        course_id=c["STA210"], uploader_id=demo.id),
        models.Material(title="Process Scheduling & Deadlocks",
                        description="FCFS, SJF, Round Robin, Banker's algorithm.",
                        tags="operating systems, scheduling, deadlock",
                        kind="slides", url="https://example.com/os.pdf",
                        course_id=c["CSC310"], uploader_id=demo.id),
    ]
    db.add_all(materials)
    db.commit()

    # A sample study group
    group = models.StudyGroup(
        name="CSC301 Study Squad",
        description="Weekly revision sessions for Data Structures",
        course_id=c["CSC301"],
        owner_id=demo.id,
    )
    db.add(group)
    db.commit()
    db.add(models.GroupMember(group_id=group.id, user_id=demo.id))
    db.commit()

    recommender.build_index(db)
    print("Seeded. Login: demo@studyhub.ai / demo1234")
    print("Demo user is admin — Moderation page is visible in the sidebar.")

db.close()
