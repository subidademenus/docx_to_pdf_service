import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, PlainTextResponse

app = FastAPI()

@app.get("/health")
def health():
    v = subprocess.run(
        ["soffice", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    ).stdout.strip()
    return {
        "ok": True,
        "version": "FINAL-FIX",
        "soffice": v
    }

@app.post("/convert")
async def convert(file: UploadFile = File(...)):

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

    try:
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
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env
            )

            if p.returncode != 0:
                return PlainTextResponse(
                    "LibreOffice failed:\n" + p.stdout,
                    status_code=500
                )

            pdf_path = None
            for f in os.listdir(tmp):
                if f.lower().endswith(".pdf"):
                    pdf_path = os.path.join(tmp, f)
                    break

            if not pdf_path or not os.path.exists(pdf_path):
                return PlainTextResponse(
                    "PDF no generado\n" + p.stdout,
                    status_code=500
                )

            # 🔥 CLAVE: leer el PDF a memoria
            with open(pdf_path, "rb") as pdf:
                pdf_bytes = pdf.read()

        # 🔥 devolver bytes, NO archivo
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=output.pdf"
            }
        )

    except Exception as e:
        return PlainTextResponse(
            "Server exception:\n" + str(e),
            status_code=500
        )
