#!/bin/sh
# Generate .htpasswd and auth snippet only when BASIC_AUTH_USER is set
AUTH_SNIPPET=/etc/nginx/auth.conf

if [ -n "$BASIC_AUTH_USER" ] && [ -n "$BASIC_AUTH_PASSWORD" ]; then
  htpasswd -cb /etc/nginx/.htpasswd "$BASIC_AUTH_USER" "$BASIC_AUTH_PASSWORD"
  cat > "$AUTH_SNIPPET" <<'CONF'
auth_basic "Sovereign";
auth_basic_user_file /etc/nginx/.htpasswd;
CONF
  echo "Basic auth enabled for user: $BASIC_AUTH_USER"
else
  : > "$AUTH_SNIPPET"
  echo "Basic auth disabled"
fi

exec nginx -g 'daemon off;'
