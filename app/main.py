from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app import llm, parsing, rate_estimate, storage

BASE_DIR = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
RATE_OPTIONS = list(range(1000, 10001, 500))
REMOTE_OPTIONS = ["フルリモート", "一部リモート", "常駐"]
WEEKLY_DAYS_OPTIONS = ["週1日", "週2日", "週3日", "週4日", "週5日(フルタイム)"]
OUTCOME_OPTIONS = ["エントリー見送り", "書類選考で見送り", "商談で見送り", "オファー", "オファー辞退"]

app = FastAPI(title="job-fit-agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def format_jst(iso_timestamp: str) -> str:
    dt = datetime.fromisoformat(iso_timestamp).astimezone(JST)
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["jst"] = format_jst


_MEETS_STYLES = {
    "○": ("ok", "○"),
    "△": ("partial", "△"),
}
_MEETS_DEFAULT_STYLE = ("ng", "×")


def _meets_style(value: object) -> tuple[str, str]:
    if value is True:
        value = "○"
    return _MEETS_STYLES.get(value, _MEETS_DEFAULT_STYLE)


def meets_class(value: object) -> str:
    return _meets_style(value)[0]


def meets_symbol(value: object) -> str:
    return _meets_style(value)[1]


templates.env.filters["meets_class"] = meets_class
templates.env.filters["meets_symbol"] = meets_symbol


_OUTCOME_BADGE_CLASSES = {
    "オファー": "accepted",
    "オファー辞退": "declined",
    "エントリー見送り": "declined",
    "書類選考で見送り": "rejected",
    "商談で見送り": "meeting-declined",
}
_OUTCOME_BADGE_DEFAULT_CLASS = "rejected"


def outcome_badge_class(value: str) -> str:
    if not value:
        return ""
    return _OUTCOME_BADGE_CLASSES.get(value, _OUTCOME_BADGE_DEFAULT_CLASS)


templates.env.filters["outcome_badge_class"] = outcome_badge_class


def is_ajax(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


def ajax_or_redirect(
    request: Request, json_data: dict, redirect_url: str, status_code: int = 200
) -> JSONResponse | RedirectResponse:
    """Ajaxリクエストにはjson_dataを、通常のフォーム送信にはredirect_urlへのリダイレクトを返す。"""
    if is_ajax(request):
        return JSONResponse(json_data, status_code=status_code)
    return RedirectResponse(
        url=redirect_url, status_code=303 if status_code == 200 else status_code
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    skill_sheet = storage.load_skill_sheet()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"has_skill_sheet": skill_sheet is not None, "result": None},
    )


def _skill_sheet_context(error: str | None = None, saved: bool = False) -> dict:
    return {
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
        request, "skill_sheet.html", _skill_sheet_context(saved=saved)
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
                request,
                "skill_sheet.html",
                _skill_sheet_context(error=str(e)),
                status_code=400,
            )
    else:
        text = manual_text

    storage.save_skill_sheet(text)
    return ajax_or_redirect(
        request, {"ok": True, "skill_sheet_text": text}, "/skill-sheet?saved=1"
    )


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
    return ajax_or_redirect(request, {"ok": True}, "/skill-sheet?saved=1")


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
    error = None
    result = None

    if job_posting_file is not None and job_posting_file.filename:
        content = await job_posting_file.read()
        try:
            posting_text = parsing.extract_text(job_posting_file.filename, content)
        except ValueError as e:
            error = str(e)

    if not error:
        if not posting_text.strip():
            error = "求人票のテキストを入力するかファイルを選択してください。"
        else:
            try:
                result = await run_in_threadpool(
                    llm.evaluate, skill_sheet, work_style_text, posting_text
                )
            except Exception as e:  # noqa: BLE001
                error = str(e)
            else:
                try:
                    storage.append_history(
                        job_title or "(タイトル未入力)", posting_text, result
                    )
                except Exception as e:  # noqa: BLE001
                    error = f"判定結果は表示されていますが、履歴への保存に失敗しました: {e}"

    return templates.TemplateResponse(
        request,
        "index.html",
        {
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
    rate = rate_estimate.estimate_hourly_rate(all_entries)
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "entries": entries,
            "page": page,
            "total_pages": total_pages,
            "sort": sort,
            "outcome_options": OUTCOME_OPTIONS,
            "rate": rate,
            "rate_min_fit_score": rate_estimate.MIN_FIT_SCORE,
        },
    )


@app.post("/history/{entry_id}/outcome")
async def set_history_outcome(
    request: Request, entry_id: str, outcome: str = Form(""), reason: str = Form("")
):
    if outcome and outcome not in OUTCOME_OPTIONS:
        return ajax_or_redirect(
            request, {"ok": False, "error": "不正な選考結果です"}, "/history", status_code=400
        )

    updated = storage.update_history_outcome(entry_id, outcome, reason)
    if not updated:
        return ajax_or_redirect(
            request,
            {"ok": False, "error": "該当する履歴が見つかりません"},
            "/history",
            status_code=404,
        )

    return ajax_or_redirect(request, {"ok": True}, "/history")
