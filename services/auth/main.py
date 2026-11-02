"""auth-service: ro'yxatdan o'tish, tizimga kirish va JWT token berish."""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auth.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(engine)
app = FastAPI(title="EcoCalc auth-service", version="1.0.0")
bearer = HTTPBearer()


def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class RegisterIn(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(..., min_length=2)
    password: str = Field(..., min_length=6)


class LoginIn(BaseModel):
    email: str
    password: str


def make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.full_name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "auth"}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterIn, s: Session = Depends(db)):
    if s.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "Bu email allaqachon ro'yxatdan o'tgan")
    pw = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = User(email=body.email.lower(), full_name=body.full_name, password_hash=pw)
    s.add(user)
    s.commit()
    s.refresh(user)
    return {"access_token": make_token(user), "token_type": "bearer"}


@app.post("/api/auth/login")
def login(body: LoginIn, s: Session = Depends(db)):
    user = s.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "Email yoki parol noto'g'ri")
    return {"access_token": make_token(user), "token_type": "bearer"}


@app.get("/api/auth/me")
def me(cred: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        data = jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token yaroqsiz")
    return {"id": int(data["sub"]), "email": data["email"], "name": data["name"]}
