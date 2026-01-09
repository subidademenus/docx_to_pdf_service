<?php
require_once 'config.php';
require_once 'vendor/autoload.php';

use PhpOffice\PhpWord\IOFactory;
use PhpOffice\PhpWord\PhpWord;

// carpetas
$inputDir  = __DIR__ . '/uploads/input/';
$outputDir = __DIR__ . '/uploads/output/';
$templateFile = __DIR__ . '/plantilla/plantilla.docx';

foreach ([$inputDir, $outputDir] as $dir) {
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }
}

$mensaje = '';
$pdfFinal = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['docx'])) {

    if ($_FILES['docx']['error'] !== 0) {
        $mensaje = '❌ Error al subir el archivo.';
    } else {

        $ext = strtolower(pathinfo($_FILES['docx']['name'], PATHINFO_EXTENSION));

        if ($ext !== 'docx') {
            $mensaje = '❌ Solo se permiten archivos .docx';
        } else {

            $nombreOriginal = $_FILES['docx']['name'];
            $hash = uniqid();
            $docxInput = $inputDir . $hash . '.docx';
            move_uploaded_file($_FILES['docx']['tmp_name'], $docxInput);

            // insertar registro
            $stmt = $mysqli->prepare("
                INSERT INTO documentos (nombre_original, docx_generado, pdf_generado, ip_usuario)
                VALUES (?, '', '', ?)
            ");
            $ip = $_SERVER['REMOTE_ADDR'] ?? '';
            $stmt->bind_param('ss', $nombreOriginal, $ip);
            $stmt->execute();
            $idDoc = $stmt->insert_id;
            $stmt->close();

            try {
                // cargar plantilla
                $plantilla = IOFactory::load($templateFile);
                $usuarioDoc = IOFactory::load($docxInput);

                // copiar contenido
                foreach ($usuarioDoc->getSections() as $section) {
                    $newSection = $plantilla->addSection();
                    foreach ($section->getElements() as $element) {
                        $newSection->addElement($element);
                    }
                }

                // guardar DOCX final
                $docxFinal = $outputDir . "doc_{$idDoc}.docx";
                $writer = IOFactory::createWriter($plantilla, 'Word2007');
                $writer->save($docxFinal);

                // convertir a PDF
                $cmd = "libreoffice --headless --convert-to pdf "
                     . escapeshellarg($docxFinal)
                     . " --outdir "
                     . escapeshellarg($outputDir);
                exec($cmd);

                $pdfFinal = $outputDir . "doc_{$idDoc}.pdf";

                // actualizar BD
                $stmt = $mysqli->prepare("
                    UPDATE documentos
                    SET docx_generado = ?, pdf_generado = ?, estado = 'procesado'
                    WHERE id = ?
                ");
                $stmt->bind_param('ssi', $docxFinal, $pdfFinal, $idDoc);
                $stmt->execute();
                $stmt->close();

                $mensaje = '✅ Documento generado correctamente';

            } catch (Exception $e) {

                $stmt = $mysqli->prepare("
                    UPDATE documentos SET estado = 'error' WHERE id = ?
                ");
                $stmt->bind_param('i', $idDoc);
                $stmt->execute();
                $stmt->close();

                $mensaje = '❌ Error al procesar el documento';
            }
        }
    }
}
?>
<!-- HTML igual al anterior -->

<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Generar Documento Membretado</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>

<div class="container">
    <img src="images/logo.png" alt="Logo" class="logo">

    <h1>Documento Membretado</h1>
    <p class="subtitle">
        Sube tu archivo Word y lo convertimos en un documento listo para imprimir.
    </p>

    <?php if ($mensaje): ?>
        <div class="mensaje"><?= $mensaje ?></div>
    <?php endif; ?>

    <form method="POST" enctype="multipart/form-data" class="formulario">
        <input type="file" name="docx" accept=".docx" required>
        <button type="submit">Subir Documento</button>
    </form>
</div>




</body>
</html>
