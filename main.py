import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, PlainTextResponse

app = FastAPI()


@app.get("/health")
def health():
    # Verifica que exista soffice y su versión
    try:
        p = subprocess.run(["soffice", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return {"ok": True, "soffice": p.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    # Guardamos y convertimos. Si algo falla, devolvemos texto con el error real.
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
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", tmp,
                in_path,
            ]

            p = subprocess.run(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            if p.returncode != 0:
                return PlainTextResponse("LibreOffice failed:\n" + p.stdout, status_code=500)

            pdf_path = os.path.join(tmp, "input.pdf")
            if not os.path.exists(pdf_path):
                return PlainTextResponse("No PDF generated.\nOutput:\n" + p.stdout, status_code=500)

            return FileResponse(pdf_path, media_type="application/pdf", filename="output.pdf")

    except Exception as e:
        return PlainTextResponse("Server exception:\n" + str(e), status_code=500)
