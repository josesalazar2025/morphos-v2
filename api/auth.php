<?php

session_start();
header('Content-Type: application/json; charset=utf-8');

// Verificar estado de sesión (GET)
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    echo json_encode([
        'autenticado' => isset($_SESSION['morphos_usuario']),
        'nombre' => $_SESSION['morphos_nombre'] ?? null,
    ]);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Método no permitido.']);
    exit;
}

require __DIR__ . '/conexion.php';

if (!$conexion) {
    http_response_code(503);
    echo json_encode(['error' => 'Error de conexión con la base de datos.']);
    exit;
}

$cuerpo = json_decode(file_get_contents('php://input'), true) ?? [];
$accion = $cuerpo['accion'] ?? '';

switch ($accion) {

    case 'login':
        $email = trim($cuerpo['email'] ?? '');
        $password = $cuerpo['password'] ?? '';

        if (!$email || !$password) {
            http_response_code(422);
            echo json_encode(['error' => 'Email y contraseña son requeridos.']);
            exit;
        }

        $stmt = $conexion->prepare("SELECT id, nombre, email, password FROM usuarios WHERE email = :email LIMIT 1");
        $stmt->bindParam(':email', $email);
        $stmt->execute();
        $usuario = $stmt->fetch(PDO::FETCH_ASSOC);

        if ($usuario && password_verify($password, $usuario['password'])) {
            $_SESSION['morphos_usuario'] = $usuario['email'];
            $_SESSION['morphos_nombre'] = $usuario['nombre'];
            echo json_encode(['ok' => true, 'nombre' => $usuario['nombre']]);
        } else {
            http_response_code(401);
            echo json_encode(['error' => 'Email o contraseña incorrectos.']);
        }
        break;

    case 'registro':
        $nombre = trim($cuerpo['nombre'] ?? '');
        $apellido = trim($cuerpo['apellido'] ?? '');
        $email = trim($cuerpo['email'] ?? '');
        $password = $cuerpo['password'] ?? '';

        if (!$nombre || !$apellido || !$email || !$password) {
            http_response_code(422);
            echo json_encode(['error' => 'Todos los campos son requeridos.']);
            exit;
        }

        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            http_response_code(422);
            echo json_encode(['error' => 'El email no es válido.']);
            exit;
        }

        if (strlen($password) < 6) {
            http_response_code(422);
            echo json_encode(['error' => 'La contraseña debe tener al menos 6 caracteres.']);
            exit;
        }

        $stmt = $conexion->prepare("SELECT id FROM usuarios WHERE email = :email LIMIT 1");
        $stmt->bindParam(':email', $email);
        $stmt->execute();
        if ($stmt->fetch()) {
            http_response_code(409);
            echo json_encode(['error' => 'Ya existe una cuenta con ese email.']);
            exit;
        }

        $hash = password_hash($password, PASSWORD_DEFAULT);
        $stmt = $conexion->prepare(
            "INSERT INTO usuarios (nombre, apellido, email, password) VALUES (:nombre, :apellido, :email, :password)"
        );
        $stmt->bindParam(':nombre', $nombre);
        $stmt->bindParam(':apellido', $apellido);
        $stmt->bindParam(':email', $email);
        $stmt->bindParam(':password', $hash);
        $stmt->execute();

        $_SESSION['morphos_usuario'] = $email;
        $_SESSION['morphos_nombre'] = $nombre;
        echo json_encode(['ok' => true, 'nombre' => $nombre]);
        break;

    case 'logout':
        session_destroy();
        echo json_encode(['ok' => true]);
        break;

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Acción no válida.']);
}
