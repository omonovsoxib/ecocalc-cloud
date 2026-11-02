"""project-service: foydalanuvchi loyihalari va yillik pul oqimlarini saqlaydi."""
import os
from typing import List

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./project.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
CALC_URL = os.getenv("CALC_URL", "http://calc-service:8000")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), default="")
    investment = Column(Float, nullable=False)
    rate = Column(Float, nullable=False)
    revenues = Column(JSON, nullable=False)   # har yil daromadi
    costs = Column(JSON, nullable=False)      # har yil xarajati
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(engine)
app = FastAPI(title="EcoCalc project-service", version="1.0.0")
bearer = HTTPBearer()


def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    try:
        return int(jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])["sub"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token yaroqsiz")


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=2)
    description: str = ""
    investment: float = Field(..., gt=0)
    rate: float = Field(..., ge=0, lt=1)
    revenues: List[float] = Field(..., min_length=1)
    costs: List[float] = Field(..., min_length=1)


def to_dict(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "investment": p.investment, "rate": p.rate,
        "revenues": p.revenues, "costs": p.costs,
        "cash_flows": [r - c for r, c in zip(p.revenues, p.costs)],
    }


def get_owned(s: Session, pid: int, uid: int) -> Project:
    p = s.get(Project, pid)
    if not p or p.owner_id != uid:
        raise HTTPException(404, "Loyiha topilmadi")
    return p


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "project"}


@app.get("/api/projects")
def list_projects(uid: int = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(Project).where(Project.owner_id == uid).order_by(Project.id.desc()))
    return [to_dict(p) for p in rows]


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, uid: int = Depends(current_user), s: Session = Depends(db)):
    if len(body.revenues) != len(body.costs):
        raise HTTPException(422, "Daromad va xarajat yillari soni teng bo'lishi kerak")
    p = Project(owner_id=uid, **body.model_dump())
    s.add(p)
    s.commit()
    s.refresh(p)
    return to_dict(p)


@app.get("/api/projects/{pid}")
def get_project(pid: int, uid: int = Depends(current_user), s: Session = Depends(db)):
    return to_dict(get_owned(s, pid, uid))


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: int, uid: int = Depends(current_user), s: Session = Depends(db)):
    s.delete(get_owned(s, pid, uid))
    s.commit()


@app.get("/api/projects/{pid}/evaluate")
def evaluate(pid: int, uid: int = Depends(current_user), s: Session = Depends(db)):
    """Loyihani calc-service'ga yuborib, natijani qaytaradi (xizmatlararo chaqiruv)."""
    d = to_dict(get_owned(s, pid, uid))
    r = httpx.post(f"{CALC_URL}/api/calc", json={
        "investment": d["investment"], "rate": d["rate"], "cash_flows": d["cash_flows"]}, timeout=10)
    r.raise_for_status()
    return {"project": d, "result": r.json()}
