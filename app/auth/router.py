from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user, get_db, get_user_primary_role
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.auth.security import create_access_token, hash_password, verify_password
from app.models import Role, User


router = APIRouter(prefix="/auth", tags=["Auth"])

ALLOWED_ROLES = ["admin", "developer", "viewer"]


def build_auth_response(user: User) -> dict:
    role = get_user_primary_role(user)

    access_token = create_access_token(
        {
            "sub": user.id,
            "email": user.email,
            "role": role,
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": role,
        },
    }


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db=Depends(get_db)):
    email = payload.email.lower().strip()

    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists",
        )

    user_count = db.query(User).count()

    requested_role = payload.role

    if not requested_role:
        requested_role = "admin" if user_count == 0 else "viewer"

    if requested_role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role",
        )

    role = db.query(Role).filter(Role.name == requested_role).first()

    if not role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Role not found. Please seed roles first.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )

    user.roles.append(role)

    db.add(user)
    db.commit()
    db.refresh(user)

    return build_auth_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db=Depends(get_db)):
    email = payload.email.lower().strip()

    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return build_auth_response(user)


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": get_user_primary_role(current_user),
    }