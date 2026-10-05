from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import shutil
import copy

from pypdf import PdfReader, PdfWriter, PageObject, Transformation

app = FastAPI(title="COPRIVIN Office to PDF Converter", version="2.0")

ALLOWED = {".docx", ".xlsx", ".xls"}

@app.get("/health")
def health():
    return {"ok": True, "formats": ["docx", "xlsx", "xls"]}


def _run_libreoffice(src: Path, out_dir: Path) -> Path:
    candidates = ["libreoffice", "soffice"]
    exe = next((x for x in candidates if shutil.which(x)), None)
    if not exe:
        raise RuntimeError("LibreOffice no está instalado en el servicio.")

    cmd = [
        exe,
        "--headless",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--nofirststartwizard",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        str(src),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError("LibreOffice no pudo convertir el archivo: " + proc.stdout[-1500:])

    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists() or pdf.stat().st_size < 100:
        # Algunos nombres pueden normalizarse; toma el PDF más reciente del directorio.
        pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not pdfs:
            raise RuntimeError("LibreOffice no generó un PDF.")
        pdf = pdfs[0]
    return pdf


def _overlay_template(content_pdf: Path, template_pdf: Path) -> bytes:
    content = PdfReader(str(content_pdf))
    template = PdfReader(str(template_pdf))
    if not template.pages:
        raise RuntimeError("La plantilla PDF no contiene páginas.")

    base_template = template.pages[0]
    writer = PdfWriter()

    for src_page in content.pages:
        w = float(src_page.mediabox.width)
        h = float(src_page.mediabox.height)

        bg = copy.deepcopy(base_template)
        tw = float(bg.mediabox.width)
        th = float(bg.mediabox.height)
        if tw <= 0 or th <= 0:
            raise RuntimeError("La plantilla PDF tiene dimensiones inválidas.")

        # Crea página final con el tamaño exacto de la página convertida.
        final = PageObject.create_blank_page(width=w, height=h)

        # Ajusta la plantilla al tamaño exacto de la página.
        sx = w / tw
        sy = h / th
        bg.add_transformation(Transformation().scale(sx=sx, sy=sy))
        bg.mediabox.upper_right = (w, h)

        # Plantilla debajo; contenido del Office encima.
        final.merge_page(bg)
        final.merge_page(src_page)
        writer.add_page(final)

    from io import BytesIO
    bio = BytesIO()
    writer.write(bio)
    return bio.getvalue()


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    template: UploadFile = File(...),
):
    filename = file.filename or "documento"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail="Solo DOCX, XLSX o XLS")

    if not (template.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="La plantilla debe ser PDF")

    with TemporaryDirectory(prefix="coprivin_conv_") as tmp:
        tmpdir = Path(tmp)
        src = tmpdir / ("documento" + ext)
        tpl = tmpdir / "plantilla.pdf"

        src.write_bytes(await file.read())
        tpl.write_bytes(await template.read())

        if src.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Archivo vacío")
        if tpl.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Plantilla vacía")

        try:
            converted = _run_libreoffice(src, tmpdir)
            result = _overlay_template(converted, tpl)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="La conversión excedió el tiempo máximo")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        if not result.startswith(b"%PDF"):
            raise HTTPException(status_code=500, detail="No se generó un PDF válido")

        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="documento_membretado.pdf"'},
        )
