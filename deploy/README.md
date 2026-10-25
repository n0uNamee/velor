# Telegram production: согласование и запуск

Эти файлы — локальные примеры конфигурации. Хостинг, TLS, bot/menu и deployment не создавались и не проверялись. Работающий localhost — отдельный demo checkpoint.

Для одного согласованного запуска нужны:

1. Выбранный hosting и публичный HTTPS URL. На нём раздавать `frontend/dist`, а `/api` проксировать на backend `127.0.0.1:8000`. Vite `:5173` — сервер разработки; production FastAPI сейчас не раздаёт frontend/TLS. Пример — `nginx.conf.example`; домен и certificate paths являются placeholder.
2. Отдельный VÉLOR bot и его server-only token. Нельзя использовать чужой timing-bot. Существующий токен передаётся через секреты hosting либо `/etc/velor/backend.env` с правами 600, не frontend и не Git. Пример — `backend.env.example`: production, dev auth выключен, paid calls выключены. Без Telegram token production backend откажется стартовать.
3. В BotFather настроить Main Mini App/menu URL на согласованный HTTPS адрес; альтернативно явное изменение menu через `setChatMenuButton`. Никакой такой внешний вызов здесь не выполнялся.
4. Постоянный writable `VELOR_DATA_DIR` для SQLite, uploads и provider ledger, плюс **один backend worker**. Locks, jobs и generation tokens находятся в одном процессе. Пример — `velor.service.example`; пользователь и каталоги должны существовать. Незавершённые jobs после restart становятся failed, платные запросы не повторяются.
5. Проверить реальный запуск внутри Telegram: frontend передаёт raw initData; backend проверяет HMAC/срок действия и разделяет пользователей. Проверить profile/upload/catalog/editor/save и отказ dev auth. Это ещё не выполнено в Telegram.

До отдельного решения оставить `VELOR_MODE=demo`, `VELOR_ALLOW_PAID_REQUESTS=0`. Разрешённые $2 относятся к суммарным локальным проверкам; $3 для возможной демонстрации не разрешены к расходованию автоматически. Публичный hosting, bot/menu изменения и расходы требуют согласования; примеры не выполняют их.

Официальные требования: [Telegram Mini Apps](https://core.telegram.org/bots/webapps), [HTTPS WebAppInfo](https://core.telegram.org/bots/api#webappinfo), [menu configuration](https://core.telegram.org/bots/api#setchatmenubutton).
