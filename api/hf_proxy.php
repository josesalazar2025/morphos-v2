<?php
header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); exit; }

$hfKey = $_ENV['HF_API_KEY'] ?? $_SERVER['HF_API_KEY'] ?? getenv('HF_API_KEY') ?? '';

if (!$hfKey && file_exists(__DIR__ . '/.env')) {
    foreach (file(__DIR__ . '/.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with($line, 'HF_API_KEY=')) { $hfKey = trim(substr($line, 11)); break; }
    }
}

if (!$hfKey) { http_response_code(503); echo json_encode(['error' => 'Servicio no configurado.']); exit; }

$body = json_decode(file_get_contents('php://input'), true);
$SPACE = 'https://blackmistcode-morphos-medgemma.hf.space/gradio_api';
$auth = ['Content-Type: application/json', "Authorization: Bearer $hfKey"];

set_time_limit(120);

function hf_get(string $url, array $headers, ?string $post = null): array {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => $headers, CURLOPT_TIMEOUT => 120]);
    if ($post !== null) { curl_setopt($ch, CURLOPT_POST, true); curl_setopt($ch, CURLOPT_POSTFIELDS, $post); }
    return [curl_exec($ch), curl_getinfo($ch, CURLINFO_HTTP_CODE)];
}

// Upload a data URL to the Gradio /upload endpoint and return a FileData object,
// or fall back to the raw data URL format if the upload fails.
function uploadImagen(string $space, string $hfKey, string $dataUrl): ?array {
    if (!preg_match('/^data:(image\/[\w+]+);base64,(.+)$/s', $dataUrl, $m)) return null;
    $mimeType = $m[1];
    $ext = explode('/', $mimeType)[1] ?? 'jpg';
    $binary = base64_decode($m[2]);
    if ($binary === false) return null;

    $boundary = bin2hex(random_bytes(16));
    $body = "--$boundary\r\n"
        . "Content-Disposition: form-data; name=\"files\"; filename=\"image.$ext\"\r\n"
        . "Content-Type: $mimeType\r\n\r\n"
        . $binary
        . "\r\n--$boundary--\r\n";

    $ch = curl_init("$space/upload");
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => [
            "Authorization: Bearer $hfKey",
            "Content-Type: multipart/form-data; boundary=$boundary",
        ],
        CURLOPT_TIMEOUT => 60,
    ]);
    $result = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($code >= 400 || !$result) {
        // Fall back: pass as data URL directly (older Gradio versions accept this)
        return ['url' => $dataUrl, 'orig_name' => "image.$ext", 'mime_type' => $mimeType];
    }

    $files = json_decode($result, true);
    $path = is_array($files) && isset($files[0]) ? $files[0] : null;
    if (!$path) {
        return ['url' => $dataUrl, 'orig_name' => "image.$ext", 'mime_type' => $mimeType];
    }

    return [
        'path' => $path,
        'url' => "$space/file=" . $path,
        'orig_name' => "image.$ext",
        'mime_type' => $mimeType,
    ];
}

$rawImages = array_slice(array_values($body['images'] ?? []), 0, 4);
$data = [];
foreach ($rawImages as $img) {
    $data[] = $img ? uploadImagen($SPACE, $hfKey, $img) : null;
}
while (count($data) < 4) $data[] = null;
$data[] = $body['prompt'] ?? '';

[$submitBody, $code] = hf_get("$SPACE/call/analyze", $auth, json_encode(['data' => $data]));

if ($code >= 400) { http_response_code(502); echo json_encode(['error' => "Error Space: HTTP $code"]); exit; }

$eventId = json_decode($submitBody, true)['event_id'] ?? null;
if (!$eventId) { http_response_code(502); echo json_encode(['error' => 'No se obtuvo event_id.']); exit; }

[$stream] = hf_get("$SPACE/call/analyze/$eventId", ["Authorization: Bearer $hfKey"]);

$result = $error = null; $lastEvent = '';
foreach (explode("\n", $stream) as $raw) {
    $line = rtrim($raw, "\r");
    if (str_starts_with($line, 'event:')) $lastEvent = trim(substr($line, 6));
    elseif (str_starts_with($line, 'data:')) {
        $parsed = json_decode(trim(substr($line, 5)), true);
        if (in_array($lastEvent, ['complete', 'process_completed']))
            $result = is_array($parsed) ? $parsed[0] : ($parsed['output'] ?? $parsed);
        elseif ($lastEvent === 'error')
            $error = $parsed['error'] ?? 'Error del modelo.';
    }
}

if ($error) { http_response_code(503); echo json_encode(['error' => $error]); }
elseif ($result !== null) { echo json_encode(['text' => $result]); }
else { http_response_code(502); echo json_encode(['error' => 'Sin respuesta del modelo.']); }
