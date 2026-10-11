FROM nginx:1.29-alpine

ARG API_BASE_URL=/api

COPY frontend /usr/share/nginx/html
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

RUN find /usr/share/nginx/html -type f -name '*.html' -print0 \
    | xargs -0 sed -i "s|http://127\.0\.0\.1:8000|${API_BASE_URL}|g"

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/health
