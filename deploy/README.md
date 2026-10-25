# Telegram production: согласование и запуск

Эти файлы — локальные примеры конфигурации. Хостинг, TLS, bot/menu и deployment не создавались и не проверялись. Работающий localhost — отдельный demo checkpoint.

Для одного согласованного запуска нужны:

1. Выбранный hosting либо отдельно разрешённый временный tunnel и публичный HTTPS URL. Backend может раздавать готовый `frontend/dist` вместе с `/api`: задать `VELOR_FRONTEND_DIST` либо использовать `.venv/bin/python run_public.py` после `npm run build` в frontend. Launcher принудительно включает production, выключает dev auth и paid calls, слушает только `127.0.0.1:8000`, требует существующий Telegram token. TLS обеспечивает согласованный proxy/tunnel. Vite `:5173` наружу не выставляется. Альтернатива — раздача статических файлов через `nginx.conf.example`; домен и certificate paths являются placeholder.
2. Отдельный VÉLOR bot и его server-only token, плюс numeric IDs допущенных пользователей в `VELOR_TELEGRAM_ALLOWED_USER_IDS` через запятую. Нельзя использовать чужой timing-bot. Существующий токен передаётся через секреты hosting либо `/etc/velor/backend.env` с правами 600, не frontend и не Git. Без Telegram token или allowlist production backend откажется стартовать. После HMAC/freshness проверяется allowlist, остальные подписанные пользователи получают 403. Production docs/openapi выключены, health не раскрывает общий spending ledger.
3. В BotFather настроить Main Mini App/menu URL на согласованный HTTPS адрес; альтернативно явное изменение menu через `setChatMenuButton`. Никакой такой внешний вызов здесь не выполнялся.
4. Постоянный writable `VELOR_DATA_DIR` для SQLite, uploads и provider ledger, плюс **один backend worker**. Locks, jobs и generation tokens находятся в одном процессе. Пример — `velor.service.example`; пользователь и каталоги должны существовать. Незавершённые jobs после restart становятся failed, платные запросы не повторяются.
5. Проверить реальный запуск внутри Telegram: frontend передаёт raw initData; backend проверяет HMAC/срок действия и разделяет пользователей. Проверить profile/upload/catalog/editor/save и отказ dev auth. Это ещё не выполнено в Telegram.

Перед публикацией проверить локально: `/` возвращает built frontend, `/api/health` сообщает production; API profile/upload/request/style без auth и с `X-Dev-User` отвергаются; signed initData принимается только для нужного bot token и свежего auth_date; неизвестный `/api` остаётся 404. Затем проверить то же через согласованный HTTPS URL и настоящий Telegram. Progress использует polling, SSE не требуется. Пример production config и сервер не запускают tunnel автоматически.

До отдельного решения оставить `VELOR_MODE=demo`, `VELOR_ALLOW_PAID_REQUESTS=0`. Разрешённые $2 относятся к суммарным локальным проверкам; $3 для возможной демонстрации не разрешены к расходованию автоматически. Публичный hosting, bot/menu изменения и расходы требуют согласования; примеры не выполняют их.

В текущей сессии отдельно разрешён и запущен accountless Quick Tunnel к production entry8000. До verified Telegram allowlist entry работает fail-closed, `auth_status=locked`: никаких profile/uploads/requests или paid calls. Mac должен оставаться включённым. Не заменять existing Cloudflare Worker, не выставлять Vite. После подтверждённого ввода токена использовать `scripts/telegram_setup.py check`, затем только verified private challenge/ID и персональную кнопку; при существующем webhook identification прекращается без его изменения. Root не читает бот-токен через UI и не выводит его.

Официальные требования: [Telegram Mini Apps](https://core.telegram.org/bots/webapps), [HTTPS WebAppInfo](https://core.telegram.org/bots/api#webappinfo), [menu configuration](https://core.telegram.org/bots/api#setchatmenubutton).
