import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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

        run([
            "libreoffice", "--headless", "--nologo", "--nolockcheck",
            "--convert-to", "pdf", "--outdir", tmp, in_path
        ])

        pdf_path = os.path.join(tmp, "input.pdf")
        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=500, detail="PDF no generado")

        return FileResponse(pdf_path, media_type="application/pdf", filename="output.pdf")
