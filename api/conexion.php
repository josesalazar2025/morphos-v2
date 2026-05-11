<?php

// Try MySQL first (local XAMPP), fallback to SQLite (Docker / HF Spaces)
$dbHost = '127.0.0.1';
$dbUsuario = 'root';
$dbClave = '';
$dbNombre = 'morphos_db';
$dbPort = 3306;
$dbPath = __DIR__ . '/../data/morphos.db';

if (file_exists(__DIR__ . '/.env')) {
    foreach (file(__DIR__ . '/.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with($line, 'DB_PORT=')) $dbPort = (int) trim(substr($line, 8));
    }
}

$conexion = null;

// Attempt MySQL only if not explicitly forced to SQLite
$useSqlite = getenv('DB_FORCE_SQLITE') === '1';

if (!$useSqlite) {
    try {
        $conexion = new PDO("mysql:host=$dbHost;port=$dbPort;dbname=$dbNombre;charset=utf8mb4", $dbUsuario, $dbClave);
        $conexion->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    } catch (PDOException $e) {
        $conexion = null;
    }
}

// Fallback to SQLite
if (!$conexion) {
    try {
        $conexion = new PDO("sqlite:$dbPath");
        $conexion->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

        // Ensure users table exists (idempotent)
        $conexion->exec("CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        )");
    } catch (PDOException $e) {
        $conexion = null;
    }
}
