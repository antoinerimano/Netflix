# Security headers for every response (included by nginx/default.conf: at the server level, and
# again in each location that sets its own add_header, since that drops the server-level ones).
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'; upgrade-insecure-requests" always;
