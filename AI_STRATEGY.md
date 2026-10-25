# VÉLOR: фактическая AI-стратегия

Актуальное решение17:37 МСК: обычный сайт, Telegram не требуется. Подготовленный сценарий использует реальный датированный снимок OKNO; профиль синтетический, состояние/сохранение настоящие и изолированы сессией. Live OKNO homepage→item SSR→verified price/size/stock успешно проверен; condition и доставка неизвестны, это явно сохранено. Preview детерминированный schematic, не фотореалистичный AI render. Один реальный OpenRouter image POST завершился неопределённой ошибкой, его HTTP status не сохранился; последующий публичный Models GET получил403 и запросы остановлены. Ledger удерживает0.30 USD, actual known0.00255825, conservative remaining1.70 из разрешённых2; повторов inference нет.

## Boss1: профиль и versioned StyleBrief

Вход — постоянный профиль со style text, wardrobe/reference images и отдельный запрос. Выход — `StyleBrief` schema `1.0`: исходные тексты, provenance `profile/request/inferred`, hard/soft constraints, exclusions, бюджет, размеры, город и неизвестные значения.

Сейчас работает детерминированный локальный адаптер. Он сохраняет текстовые условия, распознаёт явно обязательные формулировки и исключения, а не обещает идеально понять вкус. Числа из свободного текста не становятся подтверждённым бюджетом: бюджет передаётся отдельным полем. Неизвестные размеры, город и бюджет остаются null. Фото хранятся локально; визуальное понимание внешней моделью не выполнено.

Local seam — `build_brief(profile, request, mode)` в `backend/app/brief.py`; server-side OpenRouter adapter — `OpenRouterProvider.analyze_brief(profile, request, local_brief)`. Structured output проходит повторную локальную Pydantic-валидацию. Явные исходные условия не теряются; inferred условия принудительно soft. На синтетическом тексте выполнен реальный успешный analysis. Фото в его payload не входят.

## Boss2: поиск и проверяемый каталог

Контракт — `await search_catalog(brief, on_source=None) -> ProductCatalog`. Search worker владеет `backend/app/search/`: общая очередь базовых источников, ровно три динамических workers, отдельные discovery/verifier/parser. Найденный источник не считается готовым парсером. Статус каждого источника передаётся в async callback и сохраняется в запросе.

Базовые 12: Ozon, Sportmaster, Stockmann, Ostin, Lime, Befree, Sela, Zarina, Love Republic, Zolla, Tvoe, Finn Flare. Нишевые кандидаты: OKNO, VOLCHOK, MECH, SHU, KRAKATAU, Sintezia, Vintage Voyage. Их доступность и наличие нельзя считать проверенными на основании списка.

Demo не обращается к магазинам. Каждый demo product принудительно помечается `is_demo=true`, `verification=demo`, `verified_at=null`, `availability=unknown`. Live результаты должны содержать реальный URL, evidence и честное состояние проверки. Неполные данные остаются неизвестными. CAPTCHA, 403 и геоблокировки не обходятся. Сетевой adapter обязан проверять URL, DNS/IP и redirects; private networks запрещены.

## Boss3: аутфиты и render

Контракты — `compose_outfits(request_id, brief, products)` и `await render_outfit(outfit, products)`. В stylist передаются только оставшиеся catalog IDs. Backend повторно проверяет все возвращённые ID, исключения и принадлежность запроса. Стилист вызывается только после нажатия пользователем.

В demo используется схематичный матовый чёрный манекен с отдельными предметами. Это композиционная визуализация, не фотореалистичная примерка и не подтверждение посадки. Пользователь меняет предмет на другой оставшийся товар той же категории. Каждое изменение увеличивает revision; render применяется только к той ревизии, с которой был запущен. Сохранить можно только готовую актуальную ревизию.

## Изоляция и честность исполнения

Пользователи разделены Telegram ID либо явным локальным dev ID. SQLite сохраняет профили, запросы, каталоги, outfits и gallery snapshots. Перезапуск не повторяет потенциально платные запросы: незавершённые задания становятся явной ошибкой.

OpenRouter brief/render adapters реализованы в `backend/app/providers.py`; модели конфигурируются, ключ остаётся server-side. Согласован общий тестовый бюджет $2 с резервом $3 для возможной демонстрации. Выполнен один анализ `google/gemini-3.8-flash` за $0.00255825; ledger консервативно удержал $0.10. Автоматические paid calls в локальном .env выключены. Реальный render `google/gemini-3.1-flash-image` остановлен перед HTTP-запросом: публичный image host через системный DNS разрешился в неглобальный `198.18.0.x`. Guard не ослаблялся, VPN не менялся.

BackendImageProvider связывает renderer с одним центральным provider ledger. Images endpoint принимает реальные публичные карточки выбранных товаров и синтетический матовый манекен; wardrobe/reference uploads туда не допускаются. Один render за вызов, 1K, n=1, без автоматических повторов. Разрешённый live mode ограничивает автоматическую композицию одним аутфитом для контроля расходов. Галерея и revision guard сохраняются независимо от типа renderer. Запуск Telegram production и работающий live search остаются отдельными непроверенными этапами.
