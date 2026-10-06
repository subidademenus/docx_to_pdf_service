from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import shutil
import copy

from pypdf import PdfReader, PdfWriter, PageObject, Transformation

app = FastAPI(title="COPRIVIN Office to PDF Converter", version="2.0")

ALLOWED = {".docx", ".xlsx", ".xls", ".pdf"}

@app.get("/health")
def health():
    return {"ok": True, "version": "4.0-pdf-auto", "formats": ["docx", "xlsx", "xls", "pdf"], "endpoint": "/convert", "pdf_auto_endpoint": "/membrete-pdf-auto"}


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
        raise HTTPException(status_code=400, detail="Solo DOCX, XLSX, XLS o PDF")

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
            if ext == ".pdf":
                converted = src
            else:
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



def _normalized_page(page):
    p = copy.deepcopy(page)
    try:
        rot = int(getattr(p, "rotation", 0) or 0) % 360
    except Exception:
        rot = 0
    if rot in (90, 180, 270) and hasattr(p, "transfer_rotation_to_content"):
        p.transfer_rotation_to_content()
    return p


def _detect_pdf_key(page) -> str:
    p = _normalized_page(page)
    w = float(p.mediabox.width)
    h = float(p.mediabox.height)
    short = min(w, h)
    long = max(w, h)
    orientation = "horizontal" if w > h else "vertical"

    tol = 12.0
    a4_short, a4_long = 595.276, 841.89
    letter_short, letter_long = 612.0, 792.0

    if abs(short - a4_short) <= tol and abs(long - a4_long) <= tol:
        paper = "a4"
    elif abs(short - letter_short) <= tol and abs(long - letter_long) <= tol:
        paper = "carta"
    else:
        mm_w = round(short * 25.4 / 72.0, 1)
        mm_h = round(long * 25.4 / 72.0, 1)
        raise RuntimeError(f"Formato PDF no soportado: {mm_w} x {mm_h} mm. Solo A4 o Carta.")

    return f"{paper}_{orientation}"


def _overlay_pdf_auto(content_pdf: Path, template_paths: dict[str, Path]) -> bytes:
    content = PdfReader(str(content_pdf))
    if not content.pages:
        raise RuntimeError("El PDF no contiene páginas.")

    template_readers = {k: PdfReader(str(v)) for k, v in template_paths.items()}
    for key, reader in template_readers.items():
        if not reader.pages:
            raise RuntimeError(f"La plantilla {key} no contiene páginas.")

    writer = PdfWriter()
    for index, raw_page in enumerate(content.pages, start=1):
        src_page = _normalized_page(raw_page)
        key = _detect_pdf_key(src_page)
        reader = template_readers.get(key)
        if reader is None:
            raise RuntimeError(f"No existe plantilla para la página {index}: {key}")

        w = float(src_page.mediabox.width)
        h = float(src_page.mediabox.height)

        bg = copy.deepcopy(reader.pages[0])
        tw = float(bg.mediabox.width)
        th = float(bg.mediabox.height)
        if tw <= 0 or th <= 0:
            raise RuntimeError("Una plantilla PDF tiene dimensiones inválidas.")

        final = PageObject.create_blank_page(width=w, height=h)
        bg.add_transformation(Transformation().scale(sx=w / tw, sy=h / th))
        bg.mediabox.upper_right = (w, h)
        final.merge_page(bg)
        final.merge_page(src_page)
        writer.add_page(final)

    from io import BytesIO
    bio = BytesIO()
    writer.write(bio)
    return bio.getvalue()


@app.post("/membrete-pdf-auto")
async def membrete_pdf_auto(
    file: UploadFile = File(...),
    a4_vertical: UploadFile = File(...),
    a4_horizontal: UploadFile = File(...),
    carta_vertical: UploadFile = File(...),
    carta_horizontal: UploadFile = File(...),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El documento debe ser PDF")

    uploads = {
        "a4_vertical": a4_vertical,
        "a4_horizontal": a4_horizontal,
        "carta_vertical": carta_vertical,
        "carta_horizontal": carta_horizontal,
    }
    for key, up in uploads.items():
        if not (up.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"La plantilla {key} debe ser PDF")

    with TemporaryDirectory(prefix="coprivin_pdf_auto_") as tmp:
        tmpdir = Path(tmp)
        src = tmpdir / "documento.pdf"
        src.write_bytes(await file.read())
        if src.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="PDF vacío")

        template_paths = {}
        for key, up in uploads.items():
            path = tmpdir / f"{key}.pdf"
            path.write_bytes(await up.read())
            if path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail=f"Plantilla {key} vacía")
            template_paths[key] = path

        try:
            result = _overlay_pdf_auto(src, template_paths)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        if not result.startswith(b"%PDF"):
            raise HTTPException(status_code=500, detail="No se generó un PDF válido")

        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="documento_membretado.pdf"'},
        )
