import os
import shutil
import subprocess
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form
from fastapi.responses import Response, PlainTextResponse

app = FastAPI()
VERSION = "membretados-template-upload-OK + watermark-stamp-v2"


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return PlainTextResponse(traceback.format_exc(), status_code=500)


@app.get("/health")
def health():
    try:
        soff = subprocess.run(
            ["soffice", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()

        pdftk_v = subprocess.run(
            ["pdftk", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()

        return {"ok": True, "version": VERSION, "soffice": soff, "pdftk": pdftk_v}
    except Exception as e:
        return {"ok": False, "version": VERSION, "error": str(e)}


def normalize_wm(wm: str) -> str:
    wm = (wm or "").strip().upper()
    return wm if wm in ("BORRADOR", "CONFIDENCIAL") else ""


def run_cmd(cmd, cwd=None, env=None, err_msg="Command failed"):
    p = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"{err_msg}:\n{p.stdout}")
    return p.stdout


def pdftk_multibackground(content_pdf: str, background_pdf: str, output_pdf: str):
    cmd = ["pdftk", content_pdf, "multibackground", background_pdf, "output", output_pdf]
    run_cmd(cmd, err_msg="PDFTK multibackground failed")
    if not os.path.exists(output_pdf):
        raise RuntimeError("PDFTK multibackground no creó el archivo final.")


def pdftk_stamp(foreground_pdf: str, stamp_pdf: str, output_pdf: str):
    cmd = ["pdftk", foreground_pdf, "stamp", stamp_pdf, "output", output_pdf]
    run_cmd(cmd, err_msg="PDFTK stamp failed")
    if not os.path.exists(output_pdf):
        raise RuntimeError("PDFTK stamp no creó el archivo final.")


def make_watermark_pdf(path_out: str, text: str):
    # Import dentro para que solo falle si de verdad se usa watermark
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except Exception as e:
        raise RuntimeError(
            "No se pudo importar reportlab. Agrega 'reportlab==4.2.2' a requirements.txt.\n"
            f"Detalle: {e}"
        )

    w, h = A4
    c = canvas.Canvas(path_out, pagesize=A4)

    # Transparencia si está disponible
    try:
        c.setFillAlpha(0.14)
    except Exception:
        pass

    c.setFont("Helvetica-Bold", 80)
    c.setFillColorRGB(0.2, 0.2, 0.2)

    c.saveState()
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, text)
    c.restoreState()

    c.showPage()
    c.save()


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),       # DOCX
    template: UploadFile = File(...),   # PDF
    watermark: str = Form(""),          # '', 'BORRADOR', 'CONFIDENCIAL'
):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")
    if not (template.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="La plantilla debe ser PDF")

    wm = normalize_wm(watermark)

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
            "--convert-to",
            "pdf",
            "--outdir",
            tmp,
            in_docx,
        ]
        p1 = subprocess.run(
            cmd_convert,
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
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

        # 2) Plantilla abajo
        final_pdf = os.path.join(tmp, "final.pdf")
        try:
            pdftk_multibackground(content_pdf, tpl_pdf, final_pdf)
        except Exception as e:
            return PlainTextResponse(str(e), status_code=500)

        # 3) Watermark arriba
        if wm:
            try:
                wm_pdf = os.path.join(tmp, "wm.pdf")
                out_pdf = os.path.join(tmp, "final_wm.pdf")
                make_watermark_pdf(wm_pdf, wm)
                pdftk_stamp(final_pdf, wm_pdf, out_pdf)
                final_pdf = out_pdf
            except Exception as e:
                return PlainTextResponse("Error aplicando watermark:\n" + str(e), status_code=500)

        with open(final_pdf, "rb") as f:
            pdf_bytes = f.read()

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=documento_membretado.pdf"},
        )
