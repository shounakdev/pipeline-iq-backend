from uuid import uuid4
from app.database import SessionLocal
from app.models import Role

db = SessionLocal()

roles = ["admin", "developer", "viewer"]

for role_name in roles:
    existing = db.query(Role).filter(Role.name == role_name).first()

    if existing:
        print(f"Role already exists: {role_name}")
    else:
        role = Role(
            id=str(uuid4()),
            name=role_name,
        )
        db.add(role)
        print(f"Created role: {role_name}")

db.commit()
db.close()

print("Roles seeded successfully.")
