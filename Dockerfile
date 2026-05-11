FROM php:8.2-apache

# Install extensions and enable Apache modules
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libzip-dev \
    unzip \
    && docker-php-ext-install pdo pdo_mysql pdo_sqlite \
    && docker-php-ext-enable pdo pdo_mysql pdo_sqlite \
    && a2enmod rewrite deflate headers expires

# Copy project
COPY . /var/www/html/

# Create data directory for SQLite and ensure permissions
RUN mkdir -p /var/www/html/data \
    && chown -R www-data:www-data /var/www/html \
    && chmod -R 755 /var/www/html

# Expose HF Spaces default port
RUN sed -i 's/Listen 80/Listen 7860/' /etc/apache2/ports.conf \
    && sed -i 's/:80/:7860/' /etc/apache2/sites-available/000-default.conf

EXPOSE 7860

# Entrypoint handles runtime initialization
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["apache2-foreground"]
