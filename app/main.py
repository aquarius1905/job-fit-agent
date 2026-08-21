from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app import llm, parsing, storage

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
RATE_OPTIONS = list(range(1000, 10001, 500))
REMOTE_OPTIONS = ["フルリモート", "一部リモート", "常駐"]
WEEKLY_DAYS_OPTIONS = ["週1日", "週2日", "週3日", "週4日", "週5日(フルタイム)"]

app = FastAPI(title="job-fit-agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def format_jst(iso_timestamp: str) -> str:
    dt = datetime.fromisoformat(iso_timestamp).astimezone(JST)
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["jst"] = format_jst


def meets_class(value: object) -> str:
    if value == "○" or value is True:
        return "ok"
    if value == "△":
        return "partial"
    return "ng"


def meets_symbol(value: object) -> str:
    if value == "○" or value is True:
        return "○"
    if value == "△":
        return "△"
    return "×"


templates.env.filters["meets_class"] = meets_class
templates.env.filters["meets_symbol"] = meets_symbol


def is_ajax(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    skill_sheet = storage.load_skill_sheet()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "has_skill_sheet": skill_sheet is not None, "result": None},
    )


def _skill_sheet_context(request: Request, error: str | None = None, saved: bool = False) -> dict:
    return {
        "request": request,
        "skill_sheet_text": storage.load_skill_sheet(),
        "work_style": storage.load_work_style(),
        "rate_options": RATE_OPTIONS,
        "remote_options": REMOTE_OPTIONS,
        "weekly_days_options": WEEKLY_DAYS_OPTIONS,
        "saved": saved,
        "error": error,
    }


@app.get("/skill-sheet", response_class=HTMLResponse)
def skill_sheet_form(request: Request, saved: bool = False):
    return templates.TemplateResponse(
        "skill_sheet.html", _skill_sheet_context(request, saved=saved)
    )


@app.post("/skill-sheet", response_class=HTMLResponse)
async def skill_sheet_upload(
    request: Request,
    file: UploadFile | None = None,
    manual_text: str = Form(""),
):
    if file is not None and file.filename:
        content = await file.read()
        try:
            text = parsing.extract_text(file.filename, content)
        except ValueError as e:
            if is_ajax(request):
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
            return templates.TemplateResponse(
                "skill_sheet.html",
                _skill_sheet_context(request, error=str(e)),
                status_code=400,
            )
    else:
        text = manual_text

    storage.save_skill_sheet(text)
    if is_ajax(request):
        return JSONResponse({"ok": True, "skill_sheet_text": text})
    return RedirectResponse(url="/skill-sheet?saved=1", status_code=303)


@app.post("/work-style", response_class=HTMLResponse)
async def work_style_upload(
    request: Request,
    remote_options: list[str] = Form([]),
    weekly_days: list[str] = Form([]),
    rate_min: str = Form(""),
    rate_max: str = Form(""),
    leader_ok: bool = Form(False),
    pm_ok: bool = Form(False),
    free_text: str = Form(""),
):
    storage.save_work_style(
        {
            "remote_options": remote_options,
            "weekly_days": weekly_days,
            "rate_min": rate_min,
            "rate_max": rate_max,
            "leader_ok": leader_ok,
            "pm_ok": pm_ok,
            "free_text": free_text,
        }
    )
    if is_ajax(request):
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/skill-sheet?saved=1", status_code=303)


@app.post("/evaluate", response_class=HTMLResponse)
async def evaluate(
    request: Request,
    job_title: str = Form(""),
    job_posting_text: str = Form(""),
    job_posting_file: UploadFile | None = None,
):
    skill_sheet = storage.load_skill_sheet()
    if not skill_sheet:
        return RedirectResponse(url="/skill-sheet", status_code=303)
    work_style_text = llm.compose_work_style_text(storage.load_work_style())

    posting_text = job_posting_text
    if job_posting_file is not None and job_posting_file.filename:
        content = await job_posting_file.read()
        posting_text = parsing.extract_text(job_posting_file.filename, content)

    error = None
    result = None
    if not posting_text.strip():
        error = "求人票のテキストを入力するかファイルを選択してください。"
    else:
        try:
            result = await run_in_threadpool(
                llm.evaluate, skill_sheet, work_style_text, posting_text
            )
            storage.append_history(job_title or "(タイトル未入力)", posting_text, result)
        except Exception as e:  # noqa: BLE001
            error = str(e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "has_skill_sheet": True,
            "result": result,
            "error": error,
            "job_title": job_title,
            "job_posting_text": posting_text,
        },
    )


HISTORY_PAGE_SIZE = 10


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, page: int = 1, sort: str = "date"):
    all_entries = storage.load_history()
    if sort == "score":
        all_entries.sort(key=lambda e: e["evaluation"]["fit_score"], reverse=True)
    else:
        sort = "date"

    total_pages = max(1, -(-len(all_entries) // HISTORY_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * HISTORY_PAGE_SIZE
    entries = all_entries[start : start + HISTORY_PAGE_SIZE]
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "entries": entries,
            "page": page,
            "total_pages": total_pages,
            "sort": sort,
        },
    )
