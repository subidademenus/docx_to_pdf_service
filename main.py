import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, PlainTextResponse

app = FastAPI()

PLANTILLA_PDF = "/app/plantilla.pdf"


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    template: UploadFile = File(...),
):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

    if not (template.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="La plantilla debe ser PDF")

    with tempfile.TemporaryDirectory() as tmp:
        in_docx = os.path.join(tmp, "input.docx")
        tpl_pdf = os.path.join(tmp, "plantilla.pdf")

        # guardar DOCX
        with open(in_docx, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # guardar plantilla RECIBIDA
        with open(tpl_pdf, "wb") as f:
            shutil.copyfileobj(template.file, f)

        env = os.environ.copy()
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        env["LANG"] = "C.UTF-8"

        # DOCX -> PDF
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

        # buscar PDF generado
        content_pdf = None
        for name in os.listdir(tmp):
            if name.lower().endswith(".pdf") and name != "plantilla.pdf":
                content_pdf = os.path.join(tmp, name)
                break

        if not content_pdf:
            return PlainTextResponse("No se generó PDF del DOCX", status_code=500)

        # aplicar membrete CON LA PLANTILLA SELECCIONADA
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


    except Exception as e:
        return PlainTextResponse("Server exception:\n" + str(e), status_code=500)

