import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

def run(cmd):
    env = os.environ.copy()
    env["HOME"] = "/tmp"
    env["TMPDIR"] = "/tmp"

    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env
    )
    if p.returncode != 0:
        raise RuntimeError(p.stdout)

@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "input.docx")

        with open(in_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            run([
                "libreoffice",
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmp,
                in_path
            ])
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"LibreOffice error:\n{e}"
            )

        pdf_path = os.path.join(tmp, "input.pdf")
        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 1000:
            raise HTTPException(
                status_code=500,
                detail="LibreOffice no generó PDF válido"
            )

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename="output.pdf"
        )
