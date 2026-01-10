import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, PlainTextResponse

app = FastAPI()

PLANTILLA_PDF = "/app/plantilla.pdf"


@app.get("/health")
def health():
    try:
        v = subprocess.run(["soffice", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout.strip()
        return {"ok": True, "soffice": v, "plantilla_exists": os.path.exists(PLANTILLA_PDF)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

    if not os.path.exists(PLANTILLA_PDF):
        return PlainTextResponse("No existe /app/plantilla.pdf en el contenedor", status_code=500)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            in_docx = os.path.join(tmp, "input.docx")
            with open(in_docx, "wb") as f:
                shutil.copyfileobj(file.file, f)

            env = os.environ.copy()
            env["HOME"] = "/tmp"
            env["TMPDIR"] = "/tmp"
            env["LANG"] = "C.UTF-8"

            # 1) Convertir DOCX -> PDF
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
            p = subprocess.run(cmd_convert, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            if p.returncode != 0:
                return PlainTextResponse("LibreOffice failed:\n" + p.stdout, status_code=500)

            # Encontrar el PDF generado (LibreOffice puede nombrarlo distinto)
            contenido_pdf = None
            for name in os.listdir(tmp):
                if name.lower().endswith(".pdf"):
                    contenido_pdf = os.path.join(tmp, name)
                    break

            if not contenido_pdf:
                return PlainTextResponse("No se generó PDF del DOCX.\nOutput:\n" + p.stdout, status_code=500)

            # 2) Aplicar membrete como fondo a TODAS las páginas
            final_pdf = os.path.join(tmp, "final.pdf")
            cmd_bg = ["pdftk", contenido_pdf, "multibackground", PLANTILLA_PDF, "output", final_pdf]
            p2 = subprocess.run(cmd_bg, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            if p2.returncode != 0 or not os.path.exists(final_pdf):
                return PlainTextResponse("PDFTK failed:\n" + p2.stdout, status_code=500)

            # 3) Devolver PDF final como bytes
            with open(final_pdf, "rb") as f:
                pdf_bytes = f.read()

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=documento_membretado.pdf"}
        )

    except Exception as e:
        return PlainTextResponse("Server exception:\n" + str(e), status_code=500)
