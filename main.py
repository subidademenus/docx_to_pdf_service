import os
import shutil
import subprocess
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import Response, PlainTextResponse

app = FastAPI()
VERSION = "membretados-template-upload-OK"

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return PlainTextResponse(traceback.format_exc(), status_code=500)

@app.get("/health")
def health():
    try:
        v = subprocess.run(["soffice", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout.strip()
        # comprobación rápida de pdftk
        p = subprocess.run(["pdftk", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return {"ok": True, "version": VERSION, "soffice": v, "pdftk": p.stdout.strip()}
    except Exception as e:
        return {"ok": False, "version": VERSION, "error": str(e)}

@app.post("/convert")
async def convert(
    file: UploadFile = File(...),        # DOCX
    template: UploadFile = File(...),    # PDF
):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")
    if not (template.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="La plantilla debe ser PDF")

    with tempfile.TemporaryDirectory() as tmp:
        in_docx = os.path.join(tmp, "input.docx")
        tpl_pdf = os.path.join(tmp, "plantilla.pdf")

        with open(in_docx, "wb") as f:
            shutil.copyfileobj(file.file, f)

        with open(tpl_pdf, "wb") as f:
            shutil.copyfileobj(template.file, f)

        env = os.environ.copy()
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        env["LANG"] = "C.UTF-8"

        # 1) DOCX -> PDF
        cmd_convert = [
            "soffice",
            "-env:UserInstallation=file:///tmp/lo-profile",
            "--headless",
            "--nologo",
            "--nolockcheck",
            "--norestore",
            "--convert-to", "pdf",
            "--outdir", tmp,
            in_docx
        ]
        p1 = subprocess.run(cmd_convert, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if p1.returncode != 0:
            return PlainTextResponse("LibreOffice failed:\n" + p1.stdout, status_code=500)

        # encontrar PDF generado
        content_pdf = None
        for name in os.listdir(tmp):
            if name.lower().endswith(".pdf") and name != "plantilla.pdf":
                content_pdf = os.path.join(tmp, name)
                break
        if not content_pdf:
            return PlainTextResponse("No se generó el PDF del DOCX.\nOutput:\n" + p1.stdout, status_code=500)

        # 2) aplicar membrete
        final_pdf = os.path.join(tmp, "final.pdf")
        cmd_bg = ["pdftk", content_pdf, "multibackground", tpl_pdf, "output", final_pdf]
        p2 = subprocess.run(cmd_bg, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if p2.returncode != 0 or not os.path.exists(final_pdf):
            return PlainTextResponse("PDFTK failed:\n" + p2.stdout, status_code=500)

        with open(final_pdf, "rb") as f:
            pdf_bytes = f.read()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=documento_membretado.pdf"}
    )
