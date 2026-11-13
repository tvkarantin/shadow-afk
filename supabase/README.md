# Развёртывание Telegram

1. Создайте или выберите проект Supabase и включите Anonymous Sign-Ins в настройках Auth. Убедитесь, что лимит анонимных регистраций подходит для ожидаемого числа установок.
2. Выполните `supabase link --project-ref <ref>`, затем `supabase db push`.
3. Создайте одного бота через BotFather от имени владельца проекта. В Supabase Edge Function Secrets задайте `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` без @, `TELEGRAM_WEBHOOK_SECRET` и `SHADOW_CRON_SECRET`. Для двух секретов используйте разные случайные строки из букв, цифр, подчёркиваний и дефисов. Токен и секреты храните вне репозитория.
4. Выполните `supabase functions deploy telegram`. Функция проверяет пользовательский токен через Supabase Auth, а для Telegram и Cron проверяет их отдельные секретные заголовки.
5. Вызовите Telegram Bot API `setWebhook` методом POST, передав URL `https://<ref>.supabase.co/functions/v1/telegram/webhook`, поле `secret_token` со значением `TELEGRAM_WEBHOOK_SECRET` и `allowed_updates` со значением `["message"]`. Используйте токен бота только в защищённом окружении владельца при регистрации webhook.
6. В Supabase Vault создайте секрет `shadow_afk_project_url` с адресом проекта без завершающего слеша и `shadow_afk_cron_secret` со значением `SHADOW_CRON_SECRET`. Миграция уже планирует вызов раз в минуту.
7. В GitHub Actions Variables задайте `SHADOW_SUPABASE_URL` и `SHADOW_SUPABASE_PUBLISHABLE_KEY` и запустите Windows x64 workflow. Для локальной сборки создайте игнорируемый файл `shadowafk/ui/telegram-config.json` с полями `url` и `publishable_key`. Для запуска из исходников можно задать переменные окружения `SHADOW_SUPABASE_URL` и `SHADOW_SUPABASE_KEY`. Клиенту нужен только публичный ключ `sb_publishable_…`.

SQL-сценарий `telegram_test.sql` проверяет две установки, повторный Start, истечение, отмену, отвязку, отсутствие доступа к чужому чату и дедупликацию. Для проверки работающего сервиса запустите две установки с отдельными профилями Windows, нажмите Start в двух личных чатах, перезапустите приложения и отправьте по одному тестовому уведомлению. Повторите Start со старой ссылкой и убедитесь, что привязка не изменилась.

Привязку, параметры уведомлений и heartbeat приложение получает из Supabase. Ссылка доступна до подтверждения только в памяти процесса. После перезапуска кнопка повторного открытия запрашивает новую ссылку. Telegram не поддерживает ключ идемпотентности для sendMessage, поэтому повторная отправка после неопределённого сетевого сбоя отключена. Сбой доставки может привести к пропуску сообщения.
