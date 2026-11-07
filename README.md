# kufar-novostroyki-radar

Почасовой сбор открытых данных объявлений о новостройках с Kufar и небольшой дашборд.

- `collector/` — сборщик (GitHub Actions, только чтение публичных страниц Kufar); данные хранятся в Cloudflare Workers KV. Worker запускает сбор через GitHub Actions каждые 30 минут с 08:00 до 00:00 по Минску и повторно проверяет каждый слот через 15 минут.
- `worker/` — Cloudflare Worker, который отдаёт дашборд по секретной ссылке.
- `config/private.enc` — настройки, зашифрованные ключом из секрета `RADAR_KEY`.

Секреты репозитория: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `RADAR_KEY`.
