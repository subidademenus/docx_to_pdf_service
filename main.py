import os
import shutil
import subprocess
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

app = FastAPI()


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    # Para ver el error real si algo falla
    return PlainTextResponse(traceback.format_exc(), status_code=500)


@app.get("/health")
def health():
    v = subprocess.run(
        ["soffice", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    ).stdout.strip()
    return {"ok": True, "version": "fixed-pdf-search-2026-01-10", "soffice": v}


@app.post("/convert", responses={200: {"content": {"application/pdf": {}}, "description": "PDF generado"}})
async def convert(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "input.docx")
        with open(in_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        env = os.environ.copy()
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        env["LANG"] = "C.UTF-8"

        cmd = [
            "soffice",
            "-env:UserInstallation=file:///tmp/lo-profile",
            "--headless",
            "--nologo",
            "--nolockcheck",
            "--norestore",
            "--convert-to", "pdf",
            "--outdir", tmp,
            in_path
        ]

        p = subprocess.run(
            cmd,
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        if p.returncode != 0:
            return PlainTextResponse("LibreOffice failed:\n" + p.stdout, status_code=500)

        # ✅ Buscar el PDF real generado (no asumir input.pdf)
        pdf_found = None
        for name in os.listdir(tmp):
            if name.lower().endswith(".pdf"):
                pdf_found = os.path.join(tmp, name)
                break

        if not pdf_found or not os.path.exists(pdf_found):
            return PlainTextResponse("No PDF generated.\nOutput:\n" + p.stdout, status_code=500)

        return FileResponse(pdf_found, media_type="application/pdf", filename="output.pdf")
