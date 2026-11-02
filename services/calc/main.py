"""calc-service: raqamli loyihalarning iqtisodiy samaradorlik ko'rsatkichlarini hisoblaydi.

Ko'rsatkichlar: NPV, IRR, ROI, PP (oddiy qoplanish muddati), DPP (diskontlangan
qoplanish muddati), PI (rentabellik indeksi).
Xizmat holatsiz (stateless): bazaga ulanmaydi, shuning uchun Kubernetes HPA
yordamida bemalol ko'paytiriladi.
"""
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="EcoCalc calc-service", version="1.0.0")


class CalcRequest(BaseModel):
    investment: float = Field(..., gt=0, description="Boshlang'ich investitsiya (I0)")
    rate: float = Field(..., ge=0, lt=1, description="Diskont stavkasi, ulushda (0.15 = 15%)")
    cash_flows: List[float] = Field(..., min_length=1, description="Har yil uchun sof pul oqimi (daromad - xarajat)")


class CalcResult(BaseModel):
    npv: float
    irr: Optional[float]
    roi: float
    pp: Optional[float]
    dpp: Optional[float]
    pi: float
    discounted_flows: List[float]
    verdict: str


def npv(rate: float, investment: float, flows: List[float]) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(flows, start=1)) - investment


def irr(investment: float, flows: List[float]) -> Optional[float]:
    """Bisektsiya usuli bilan NPV = 0 bo'ladigan stavkani topadi."""
    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo, investment, flows), npv(hi, investment, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, investment, flows)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def payback(investment: float, flows: List[float]) -> Optional[float]:
    """Investitsiya qaytadigan muddat (yilda, kasr qismi bilan)."""
    acc = 0.0
    for year, cf in enumerate(flows, start=1):
        if cf > 0 and acc + cf >= investment:
            return round(year - 1 + (investment - acc) / cf, 2)
        acc += cf
    return None


def calculate(req: CalcRequest) -> CalcResult:
    disc = [cf / (1 + req.rate) ** t for t, cf in enumerate(req.cash_flows, start=1)]
    value = sum(disc) - req.investment
    total = sum(req.cash_flows)
    r = irr(req.investment, req.cash_flows)
    verdict = "Loyiha samarali (NPV > 0)" if value > 0 else "Loyiha samarasiz (NPV <= 0)"
    return CalcResult(
        npv=round(value, 2),
        irr=round(r, 4) if r is not None else None,
        roi=round((total - req.investment) / req.investment * 100, 2),
        pp=payback(req.investment, req.cash_flows),
        dpp=payback(req.investment, disc),
        pi=round(sum(disc) / req.investment, 3),
        discounted_flows=[round(x, 2) for x in disc],
        verdict=verdict,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "calc"}


@app.post("/api/calc", response_model=CalcResult)
def calc(req: CalcRequest):
    return calculate(req)


@app.post("/api/calc/compare")
def compare(projects: List[CalcRequest]):
    results = [calculate(p) for p in projects]
    best = max(range(len(results)), key=lambda i: results[i].npv)
    return {"results": results, "best_index": best}
