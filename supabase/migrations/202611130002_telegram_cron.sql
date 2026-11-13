create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.schedule('shadow-afk-telegram', '* * * * *', $job$
    select net.http_post(
        url := u.decrypted_secret || '/functions/v1/telegram/cron',
        headers := jsonb_build_object('Content-Type','application/json','X-Shadow-Cron-Secret',s.decrypted_secret),
        body := '{}'::jsonb,
        timeout_milliseconds := 15000
    )
    from vault.decrypted_secrets u cross join vault.decrypted_secrets s
    where u.name='shadow_afk_project_url' and s.name='shadow_afk_cron_secret';
$job$);
