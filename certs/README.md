# Russian trusted CA (MinDigital)

Public root/sub CA certificates for TLS to Russian services (GigaChat API, etc.).

Source: https://gu-st.ru/content/lending/

| File | URL |
|------|-----|
| `russian_trusted_root_ca.pem` | https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt |
| `russian_trusted_sub_ca.pem` | https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt |

## Corporate MITM / FreeIPA (local only)

Directory `ca-certificates-21/` — corporate trust anchors (e.g. FreeIPA CA). **Gitignored** — copy your org CA files here locally; do not commit to the public repo.

Mounted with `./certs:/certs` in Compose; included in the runtime bundle built by `services/news/ssl.py`.

Legacy note: previously referenced `backend/Dockerfile`; news workers use volume mount + runtime bundle.
