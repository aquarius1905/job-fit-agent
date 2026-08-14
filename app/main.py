from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import llm, parsing, storage

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="job-fit-agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    skill_sheet = storage.load_skill_sheet()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "has_skill_sheet": skill_sheet is not None, "result": None},
    )


@app.get("/skill-sheet", response_class=HTMLResponse)
def skill_sheet_form(request: Request):
    return templates.TemplateResponse(
        "skill_sheet.html",
        {"request": request, "skill_sheet_text": storage.load_skill_sheet(), "error": None},
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
            return templates.TemplateResponse(
                "skill_sheet.html",
                {
                    "request": request,
                    "skill_sheet_text": storage.load_skill_sheet(),
                    "error": str(e),
                },
                status_code=400,
            )
    else:
        text = manual_text

    storage.save_skill_sheet(text)
    return RedirectResponse(url="/skill-sheet", status_code=303)


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
            result = llm.evaluate(skill_sheet, posting_text)
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


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    return templates.TemplateResponse(
        "history.html", {"request": request, "entries": storage.load_history()}
    )
