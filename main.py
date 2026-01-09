import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, PlainTextResponse

app = FastAPI()

@app.get("/health")
def health():
    try:
        p = subprocess.run(["soffice", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return {"ok": True, "soffice": p.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = os.path.join(tmp, "input.docx")
            with open(in_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            env = os.environ.copy()
            env["HOME"] = "/tmp"
            env["TMPDIR"] = "/tmp"
            env["LANG"] = "C.UTF-8"

            # ✅ usa "pdf" (más compatible)
            cmd = [
                "soffice",
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmp,
                in_path
            ]

            p = subprocess.run(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            if p.returncode != 0:
                return PlainTextResponse("LibreOffice failed:\n" + p.stdout, status_code=500)

            # LibreOffice a veces nombra distinto; buscamos el primer PDF generado
            pdf_found = None
            for name in os.listdir(tmp):
                if name.lower().endswith(".pdf"):
                    pdf_found = os.path.join(tmp, name)
                    break

            if not pdf_found or not os.path.exists(pdf_found):
                return PlainTextResponse("No PDF generated.\nOutput:\n" + p.stdout, status_code=500)

            return FileResponse(pdf_found, media_type="application/pdf", filename="output.pdf")

    except Exception as e:
        return PlainTextResponse("Server exception:\n" + str(e), status_code=500)
