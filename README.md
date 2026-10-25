# VÉLOR

Telegram Mini App AI-стилист. Локальный прототип: постоянный профиль → запрос → каталог → удаление неподходящих товаров → стилист → редактор аутфита → сохранённая галерея.

Текущий режим по умолчанию — **DEMO**. Демонстрационные товары, остатки, цены и схематичный render не являются проверенной live-выдачей магазина или фотографией примерки. OpenRouter structured analysis прошёл одну реальную проверку на синтетическом профиле. Live search/render пока имеют сетевые ограничения; Telegram production не проверялся.

## Локальный запуск

Из `/Users/alik/VELOR`:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_backend.py
```

В другом терминале:

```sh
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Frontend: http://127.0.0.1:5173. API: http://127.0.0.1:8000/api/health. OpenAPI: http://127.0.0.1:8000/docs. Vite проксирует `/api` на `:8000`. Launcher читает только локальный VÉLOR/.env, не исполняет shell-код и не выводит значения. Обычный uvicorn с `--app-dir backend` тоже работает, но сам `.env` не загружает.

Локальный auth явно задаётся заголовком `X-Dev-User: demo`. Другой идентификатор создаёт отдельного пользователя. Автоматического анонимного общего профиля нет.

## Backend и хранение

Python 3.12, FastAPI, Pydantic v2, SQLite. Общие API и модели описаны в [CONTRACTS.md](CONTRACTS.md). Локальная база — `data/velor.sqlite3`, фото — `data/uploads/`; эти данные исключены из Git. `VELOR_DATA_DIR` меняет папку хранения. API не возвращает файловые пути и не выдаёт чужие фото.

Профиль сохраняется отдельно от запросов. Каждый запрос хранит свой versioned StyleBrief, каталог, исключения и ревизии аутфитов. Галерея сохраняет выбранный снимок; дальнейшее редактирование запроса его не теряет. Поздний render не может перезаписать новую ревизию.

Фото принимаются только как локальные JPEG/PNG/WebP: максимум 10 MiB и 20 мегапикселей, 24 фото в профиле/запросе, 100 файлов / 100 MiB на пользователя. Фото не отправляются внешним сервисам. `GET /api/uploads/{id}` требует auth; UI должен получить blob с заголовком auth.

## Конфигурация

| Переменная | По умолчанию | Значение |
| --- | --- | --- |
| `VELOR_ENV` | `development` | `development`, `test`, `production` |
| `VELOR_MODE` | `demo` | `demo` либо `live`; live не подключает провайдеров автоматически |
| `VELOR_DEV_AUTH` | `1` только для development | Явно разрешает локальный dev auth |
| `VELOR_DATA_DIR` | `data/` | SQLite и локальные uploads |
| `TELEGRAM_BOT_TOKEN` | отсутствует | Только для server-side проверки Telegram initData |
| `VELOR_TELEGRAM_MAX_AGE` | `3600` | Допустимый возраст initData в секундах |
| `VELOR_CORS_ORIGINS` | localhost/127.0.0.1:5173 | Разрешённые origins, через запятую |

Production использует `Authorization: tma <Telegram.WebApp.initData>`: HMAC-SHA256, constant-time comparison, срок действия, защита от дублирующих полей, числовой user ID. Поведение сверено с [официальным алгоритмом Telegram](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app). Сервер не стартует в production без bot token или с разрешённым dev auth. Реальный запуск в Telegram требует HTTPS-хостинга и привязки к боту; здесь они не выполнялись.

OpenRouter использует server-only `OPENROUTER_API_KEY`; модели конфигурируются через `VELOR_OPENROUTER_BRIEF_MODEL` и `VELOR_OPENROUTER_RENDER_MODEL`. Paid calls требуют одновременно live mode, ключ, `VELOR_ALLOW_PAID_REQUESTS=1`, положительный общий бюджет и известный резерв цены. По умолчанию автоматические paid calls выключены. Общий SQLite ledger резервирует стоимость до запроса; ошибки и неизвестный исход сохраняют резерв. Повторов нет. Кэш учитывает входные данные и ревизию. Резерв — консервативная защита приложения, не гарантия окончательного vendor billing cap при неизвестной цене.

Пользователь разрешил суммарно $2 на проверки; $3 оставлены для возможной демонстрации и не включены. Выполнен один analysis за $0.00255825, консервативно удержано $0.10. Render остановлен до HTTP-вызова из-за DNS/SSRF guard. Фото пользователя не отправлялись. Наличие `VELOR_MODE=live` само по себе не означает проверенные магазины. Состояния провайдеров и ledger видны в `/api/health`.

## Проверка

```sh
.venv/bin/python -m pytest -q
cd frontend
npm run build
```

Фактически выполненные проверки и ограничения фиксируются в `docs/VERIFICATION.md`. Live-покупки, платные API и публикация не входят в локальную проверку.

Для согласованного Telegram production подготовлены [локальные deployment examples](deploy/README.md): HTTPS frontend + same-origin API proxy, отдельный bot, server-only env и один backend worker с постоянным data volume. Эти примеры не развёрнуты и не меняют внешние сервисы.
