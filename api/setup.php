<?php

header('Content-Type: text/html; charset=utf-8');

$dbHost = '127.0.0.1';
$dbUsuario = 'root';
$dbClave = '';
$dbNombre = 'morphos_db';
$dbPort = 3306;

foreach (file(__DIR__ . '/.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with($line, 'DB_PORT=')) $dbPort = (int) trim(substr($line, 8));
}

try {
    $conexion = new PDO("mysql:host=$dbHost;port=$dbPort;charset=utf8mb4", $dbUsuario, $dbClave);
    $conexion->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    $conexion->exec("CREATE DATABASE IF NOT EXISTS `$dbNombre`");
    $conexion->exec("USE `$dbNombre`");
    $conexion->exec("
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            apellido VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ");

    echo "<p style='font-family:sans-serif;color:green'>✓ Base de datos <strong>$dbNombre</strong> y tabla <strong>usuarios</strong> listas.</p>";
    echo "<p style='font-family:sans-serif'><a href='../index.html'>← Volver a Morphos</a></p>";

} catch (PDOException $e) {
    echo "<p style='font-family:sans-serif;color:red'>Error: " . htmlspecialchars($e->getMessage()) . "</p>";
}
