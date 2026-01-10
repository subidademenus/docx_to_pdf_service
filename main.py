import os, shutil, subprocess, tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

app = FastAPI()

@app.get("/health")
def health():
    v = subprocess.run(
        ["soffice", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    ).stdout.strip()
    return {"ok": True, "version": "final-2026-01-09", "soffice": v}


@app.post(
    "/convert",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF generado"
        }
    }
)
async def convert(file: UploadFile = File(...)):

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo DOCX")

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
                "-env:UserInstallation=file:///tmp/lo-profile",
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmp,
                in_path
            ]

            p = subprocess.run(
                cmd,
                cwd=tmp,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            if p.returncode != 0:
                return PlainTextResponse(
                    "LibreOffice failed:\n" + p.stdout,
                    status_code=500
                )

            pdf_found = None
            for f in os.listdir(tmp):
                if f.lower().endswith(".pdf"):
                    pdf_found = os.path.join(tmp, f)
                    break

            if not pdf_found:
                return PlainTextResponse(
                    "No PDF generated.\nOutput:\n" + p.stdout,
                    status_code=500
                )

            return FileResponse(
                pdf_found,
                media_type="application/pdf",
                filename="output.pdf"
            )

    except Exception as e:
        return PlainTextResponse(
            "Server exception:\n" + str(e),
            status_code=500
        )
