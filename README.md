# kufar-novostroyki-radar

Почасовой сбор открытых данных объявлений о новостройках с Kufar и небольшой дашборд.

- `collector/` — сборщик (GitHub Actions по расписанию, только чтение публичных страниц Kufar); данные хранятся в Cloudflare Workers KV.
- `worker/` — Cloudflare Worker, который отдаёт дашборд по секретной ссылке.
- `config/private.enc` — настройки, зашифрованные ключом из секрета `RADAR_KEY`.

Секреты репозитория: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `RADAR_KEY`.
