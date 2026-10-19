#!/bin/sh
set -eu

ca_directory=/ca
server_directory=/server
mkdir -p "$ca_directory" "$server_directory"

if [ ! -s "$ca_directory/ca.crt" ] || [ ! -s "$server_directory/server.key" ]; then
    openssl genrsa -out /tmp/ca.key 4096
    openssl req -x509 -new -sha256 -days 3650 \
        -key /tmp/ca.key \
        -subj "/CN=HorRAGor Internal CA" \
        -out "$ca_directory/ca.crt"

    openssl genrsa -out "$server_directory/server.key" 3072
    openssl req -new \
        -key "$server_directory/server.key" \
        -subj "/CN=intelligence-api" \
        -out "$server_directory/server.csr"

    cat > "$server_directory/server.ext" <<'EOF'
subjectAltName=DNS:intelligence-api,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

    openssl x509 -req -sha256 -days 825 \
        -in "$server_directory/server.csr" \
        -CA "$ca_directory/ca.crt" \
        -CAkey /tmp/ca.key \
        -CAcreateserial \
        -extfile "$server_directory/server.ext" \
        -out "$server_directory/server.crt"
    rm -f /tmp/ca.key "$ca_directory/ca.srl" "$server_directory/server.csr" "$server_directory/server.ext"
fi

chown 10001:10001 "$server_directory/server.crt" "$server_directory/server.key"
chmod 0444 "$ca_directory/ca.crt" "$server_directory/server.crt"
chmod 0440 "$server_directory/server.key"