#!/bin/bash
set -e

DATA_DIR="/var/www/html/data"
DB_FILE="$DATA_DIR/morphos.db"

# Ensure data directory exists with correct ownership
mkdir -p "$DATA_DIR"
chown www-data:www-data "$DATA_DIR"

# Ensure SQLite database file exists so PDO can connect
touch "$DB_FILE"
chown www-data:www-data "$DB_FILE"
chmod 664 "$DB_FILE"

# Initialize SQLite schema if the table does not exist
php -r "
\$dbPath = '$DB_FILE';
try {
    \$pdo = new PDO('sqlite:' . \$dbPath);
    \$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    \$pdo->exec('CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        apellido TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )');
} catch (PDOException \$e) {
    error_log('SQLite init error: ' . \$e->getMessage());
    exit(1);
}
"

exec "$@"
