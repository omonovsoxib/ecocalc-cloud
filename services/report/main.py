"""report-service: loyiha natijasi bo'yicha PDF yoki Excel hisobot yaratadi.

Agar GCS_BUCKET o'zgaruvchisi berilgan bo'lsa, fayl Google Cloud Storage'ga ham
saqlanadi (bulutga ma'lumot joylash talabi).
"""
import io
import os
from datetime import datetime

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PROJECT_URL = os.getenv("PROJECT_URL", "http://project-service:8000")
GCS_BUCKET = os.getenv("GCS_BUCKET", "")

app = FastAPI(title="EcoCalc report-service", version="1.0.0")


def fetch(pid: int, authorization: str) -> dict:
    r = httpx.get(f"{PROJECT_URL}/api/projects/{pid}/evaluate",
                  headers={"Authorization": authorization}, timeout=15)
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()


def save_to_gcs(name: str, data: bytes, content_type: str) -> None:
    if not GCS_BUCKET:
        return
    from google.cloud import storage  # faqat bulutda kerak
    storage.Client().bucket(GCS_BUCKET).blob(f"reports/{name}").upload_from_string(data, content_type=content_type)


def rows(d: dict):
    p, res = d["project"], d["result"]
    metrics = [
        ("NPV (sof joriy qiymat)", f'{res["npv"]:,.2f}'),
        ("IRR (ichki daromadlilik)", f'{res["irr"] * 100:.2f} %' if res["irr"] is not None else "-"),
        ("ROI", f'{res["roi"]:.2f} %'),
        ("PP (qoplanish muddati)", f'{res["pp"]} yil' if res["pp"] else "qoplanmaydi"),
        ("DPP (diskontlangan)", f'{res["dpp"]} yil' if res["dpp"] else "qoplanmaydi"),
        ("PI (rentabellik indeksi)", str(res["pi"])),
    ]
    years = [(i + 1, p["revenues"][i], p["costs"][i], p["cash_flows"][i], res["discounted_flows"][i])
             for i in range(len(p["cash_flows"]))]
    return p, res, metrics, years


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "report"}


@app.get("/api/reports/{pid}.pdf")
def pdf(pid: int, authorization: str = Header(...)):
    p, res, metrics, years = rows(fetch(pid, authorization))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=p["name"])
    st = getSampleStyleSheet()
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f5"))])
    story = [
        Paragraph(f"EcoCalc Cloud hisoboti: {p['name']}", st["Title"]),
        Paragraph(f"Investitsiya: {p['investment']:,.2f} | Diskont stavkasi: {p['rate'] * 100:.1f} % | "
                  f"Sana: {datetime.now():%Y-%m-%d}", st["Normal"]),
        Spacer(1, 12),
        Table([("Ko'rsatkich", "Qiymat")] + metrics, style=style, colWidths=[220, 180]),
        Spacer(1, 12),
        Table([("Yil", "Daromad", "Xarajat", "Pul oqimi", "Diskontlangan")] +
              [tuple(f"{v:,.2f}" if isinstance(v, float) else v for v in y) for y in years], style=style),
        Spacer(1, 12),
        Paragraph(f"Xulosa: {res['verdict']}", st["Heading3"]),
    ]
    doc.build(story)
    data = buf.getvalue()
    save_to_gcs(f"project-{pid}.pdf", data, "application/pdf")
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="project-{pid}.pdf"'})


@app.get("/api/reports/{pid}.xlsx")
def xlsx(pid: int, authorization: str = Header(...)):
    p, res, metrics, years = rows(fetch(pid, authorization))
    wb = Workbook()
    ws = wb.active
    ws.title = "Natija"
    ws.append([f"EcoCalc Cloud: {p['name']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Ko'rsatkich", "Qiymat"])
    for m in metrics:
        ws.append(list(m))
    ws.append([])
    ws.append(["Yil", "Daromad", "Xarajat", "Pul oqimi", "Diskontlangan"])
    for y in years:
        ws.append(list(y))
    ws.append(["Xulosa", res["verdict"]])
    ws.column_dimensions["A"].width = 28
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    save_to_gcs(f"project-{pid}.xlsx", data, mime)
    return StreamingResponse(io.BytesIO(data), media_type=mime,
                             headers={"Content-Disposition": f'attachment; filename="project-{pid}.xlsx"'})
