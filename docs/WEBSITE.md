# Лендинг Bakunity RDP

Публичный сайт проекта находится по адресу:

```text
https://rdp.bakunity.com/
```

Лендинг является частью того же репозитория, что и server/client code. Он не требует Node.js, package manager или отдельной сборки.

## Файлы

```text
index.html
assets/styles.css
assets/app.js
assets/favicon.svg
assets/og-card.svg
site.webmanifest
robots.txt
sitemap.xml
vercel.json
```

## Принципы

- статический HTML/CSS/JavaScript;
- без аналитики и сторонних tracker scripts;
- без внешних шрифтов и runtime-зависимостей;
- адаптивная мобильная версия;
- доступная клавиатурная навигация;
- поддержка `prefers-reduced-motion`;
- ссылки на стабильный релиз и документацию;
- в публичных примерах запрещены реальные IP, usernames и machine names.

## Локальный запуск

Из корня репозитория:

```bash
python3 -m http.server 8080
```

Открыть:

```text
http://127.0.0.1:8080/
```

## Vercel

Проект разворачивается из корня репозитория как статический сайт.

Рекомендуемые настройки Vercel:

```text
Framework Preset: Other
Root Directory: ./
Build Command: пусто
Output Directory: пусто
Install Command: пусто
```

`vercel.json` добавляет:

- security headers;
- долговременный cache для `/assets/*`;
- короткие redirects `/github`, `/release` и `/docs`.

После привязки production domain проверить:

```text
https://rdp.bakunity.com/
https://rdp.bakunity.com/robots.txt
https://rdp.bakunity.com/sitemap.xml
https://rdp.bakunity.com/github
https://rdp.bakunity.com/release
```

## Контент

Актуальная версия указывается в:

- release badge в hero;
- JSON-LD `softwareVersion`;
- install commands;
- ссылках на tag documentation.

При выпуске новой версии нужно заменить старый tag во всех этих местах.

Проверка:

```bash
grep -R "v1.0.7" index.html docs/WEBSITE.md
```

## Social preview

Open Graph card:

```text
assets/og-card.svg
```

Размер canvas:

```text
1200 × 630
```

При изменении позиционирования проекта обновить одновременно:

- `<title>`;
- meta description;
- Open Graph title/description;
- Twitter title/description;
- JSON-LD description;
- `assets/og-card.svg`.

## Privacy

На сайте нельзя размещать:

- реальные публичные IP инфраструктуры;
- Telegram bot token;
- Telegram user ID владельца;
- device tokens;
- FRP token;
- pairing codes;
- реальные Windows usernames;
- реальные machine names без явной необходимости.

Использовать только нейтральные значения:

```text
SERVER_IP_OR_DOMAIN
TELEGRAM_USER_ID
PAIR_CODE
SHA256_HEX
Windows-PC-01
Office-PC
Laptop
```

## Перед merge

```bash
bash scripts/check-release.sh
```

Также вручную проверить:

- desktop layout;
- ширину 390 px;
- мобильное меню;
- переключение install steps;
- copy buttons;
- все GitHub links;
- отсутствие horizontal scroll;
- `robots.txt` и `sitemap.xml`;
- favicon и social preview metadata.


## Перенос на VPS: rdp.bakunity.com

Production-домен: `rdp.bakunity.com`. Статический лендинг хостится отдельно от RDP API и туннелей. Не публикуйте порты администрирования через этот виртуальный хост.

1. DNS: A-запись `rdp` на публичный IPv4 VPS с nginx (IPv6/AAAA — только при рабочем IPv6).
2. Размещение на VPS: `/opt/bakunity-rdp-site/releases/<release-id>`, симлинк `/opt/bakunity-rdp-site/current` на текущий релиз, nginx `root /opt/bakunity-rdp-site/current;`.
3. Веб-корень содержит `index.html`, `assets/`, `robots.txt`, `sitemap.xml`, `site.webmanifest`. `server/`, `client/`, `context/`, `scripts/` и конфигурации не публиковать.
4. Использовать конфигурацию из `deploy/nginx-rdp.bakunity.com.conf`; получить сертификат Let's Encrypt после проверки DNS, затем включить HTTPS и редирект с HTTP. Существующие nginx сайты не заменять.
5. Проверить HTTPS, заголовки, robots/sitemap, мобильную версию, Matrix animation и обновление релиза без простоя. Пока все проверки не пройдены — Vercel не удалять.

Публикация не выполнена автоматически: требуется доступ к VPS, проверка DNS и настройка TLS.
