import os
import shutil
import subprocess
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form
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

def normalize_wm(wm: str) -> str:
    wm = (wm or "").strip().upper()
    return wm if wm in ("BORRADOR", "CONFIDENCIAL") else ""

def make_watermark_pdf(path_out: str, text: str):
    # PDF A4 con texto grande en diagonal (encima)
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    w, h = A4
    c = canvas.Canvas(path_out, pagesize=A4)

    # Transparencia (si está disponible)
    try:
        c.setFillAlpha(0.15)
    except Exception:
        pass

    c.setFont("Helvetica-Bold", 80)
    c.setFillColorRGB(0.2, 0.2, 0.2)  # gris oscuro suave

    c.saveState()
    c.translate(w/2, h/2)
    c.rotate(35)
    c.drawCentredString(0, 0, text)
    c.restoreState()

    c.showPage()
    c.save()

def pdftk_stamp(foreground_pdf: str, stamp_pdf: str, output_pdf: str):
    # overlay (encima)
    cmd = ["pdftk", foreground_pdf, "stamp", stamp_pdf, "output", output_pdf]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0 or not os.path.exists(output_pdf):
        raise RuntimeError("PDFTK stamp failed:\n" + p.stdout)




@app.post("/convert")
async def convert(
    file: UploadFile = File(...),      # DOCX
    template: UploadFile = File(...),  # PDF
    watermark: str = Form(""),         # <-- NUEVO
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
        wm = normalize_wm(watermark)
if wm:
    wm_pdf = os.path.join(tmp, "wm.pdf")
    out_pdf = os.path.join(tmp, "final_wm.pdf")

    make_watermark_pdf(wm_pdf, wm)
    pdftk_stamp(final_pdf, wm_pdf, out_pdf)

    final_pdf = out_pdf  # <- ahora el final es el watermarked

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


