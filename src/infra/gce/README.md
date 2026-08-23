# GCE Docker Compose CD

The active workflow is `.github/workflows/cd-gce.yml`. It follows this sequence:

1. build and push Web, Service API and Routing API images to Docker Hub;
2. SSH to the GCE VM and upload the HTTP Nginx template plus Compose file;
3. start HTTP, issue/renew the Let's Encrypt certificate;
4. switch to HTTPS, run Service/Routing migrations and start the full stack;
5. verify public HTTPS and prune dangling images older than seven days.

Before the first run, install Docker Engine, Docker Compose v2 and OpenSSL on the
VM, authenticate the VM to Docker Hub if the repositories are private, copy
`.env.example` to `<REMOTE_APP_DIR>/.env`, fill the values and run `chmod 600 .env`.
The Service and Routing databases/Redis endpoints are deployment prerequisites and
are not created by this Compose file.

GitHub secrets:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `KAKAO_JS_API_KEY` (the domain-restricted browser key is embedded in the Web build)
- `SSH_KEY`, `HOST`, `HOST_KEY`, `USER`, `REMOTE_APP_DIR`
- `DOMAIN`, `LETSENCRYPT_EMAIL`

GitHub variable:

- `PRIVACY_DOCUMENT_VERSION`

`HOST_KEY` must contain the reviewed `known_hosts` line for the VM. The workflow
does not use `ssh-keyscan` or disable host verification. Runtime Provider/API/DB/JWT
secrets stay in the VM's `.env` and are never copied from the repository.
