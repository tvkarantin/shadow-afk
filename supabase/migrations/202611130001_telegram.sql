create table public.telegram_devices (
    owner uuid primary key references auth.users(id) on delete cascade,
    link_hash text unique,
    expires_at timestamptz,
    last_link_at timestamptz,
    chat_id bigint,
    account_name text,
    binding uuid,
    events text[] not null default array['victory','recognition','fortnite_exit','app_error','offline','summary'],
    heartbeat_at timestamptz,
    offline_reported boolean not null default false,
    last_notice_at timestamptz
);
create table public.telegram_notices (
    id bigint generated always as identity primary key,
    owner uuid not null references public.telegram_devices(owner) on delete cascade,
    binding uuid not null,
    event_key text not null,
    message text not null,
    created_at timestamptz not null default now(),
    claimed_at timestamptz,
    unique (owner, binding, event_key)
);
alter table public.telegram_devices enable row level security;
alter table public.telegram_notices enable row level security;
revoke all on public.telegram_devices, public.telegram_notices from public, anon, authenticated;
grant select, insert, update, delete on public.telegram_devices, public.telegram_notices to service_role;
grant usage on sequence public.telegram_notices_id_seq to service_role;

create function public.telegram_device(p_owner uuid, p_action text, p_data jsonb)
returns jsonb language plpgsql set search_path = '' as $$
declare
    d public.telegram_devices;
    moment timestamptz := clock_timestamp();
    kind text := p_data->>'event';
    event_key text := p_data->>'key';
    message text;
begin
    if p_action = 'begin' then
        insert into public.telegram_devices(owner) values (p_owner) on conflict do nothing;
    end if;
    select * into d from public.telegram_devices where owner = p_owner for update;
    if not found then return jsonb_build_object('state','disconnected'); end if;

    case p_action
    when 'begin' then
        if d.binding is not null then return jsonb_build_object('error','already_linked'); end if;
        if d.last_link_at > moment - interval '3 seconds' then
            return jsonb_build_object('error','rate_limited');
        end if;
        update public.telegram_devices set link_hash = p_data->>'hash',
            expires_at = moment + interval '10 minutes', last_link_at = moment
            where owner = p_owner returning * into d;
    when 'cancel' then
        update public.telegram_devices set link_hash=null, expires_at=null where owner=p_owner returning * into d;
    when 'unlink' then
        update public.telegram_devices set link_hash=null, expires_at=null, chat_id=null,
            account_name=null, binding=null, heartbeat_at=null, offline_reported=false, last_notice_at=null
            where owner=p_owner returning * into d;
        delete from public.telegram_notices where owner=p_owner;
    when 'heartbeat' then
        if d.binding is not null then
            update public.telegram_devices set heartbeat_at=moment, offline_reported=false where owner=p_owner;
        end if;
    when 'preferences' then
        if d.binding is not null then
            update public.telegram_devices set events=array(
                select distinct value from jsonb_array_elements_text(p_data->'events')
                where value in ('victory','recognition','fortnite_exit','app_error','offline','summary')
            ) where owner=p_owner returning * into d;
        end if;
    when 'notify' then
        if d.binding is null or (p_data->>'binding') is distinct from d.binding::text then
            return jsonb_build_object('error','not_linked');
        end if;
        if kind = 'test' or (kind <> 'offline' and kind = any(d.events)) then
            message := case kind
                when 'test' then '✅ Тестовое уведомление Shadow AFK'
                when 'victory' then '🏆 Подтверждённая королевская победа'
                when 'recognition' then '⚠️ Shadow AFK не смог распознать игровой экран'
                when 'fortnite_exit' then '🔴 Fortnite закрылся во время матча. Возможен сбой.'
                when 'app_error' then '❌ Ошибка Shadow AFK при обработке кадра'
                when 'summary' then format('📊 Итог сессии Shadow AFK. Матчей: %s. Завершено: %s. Время: %s с.',
                    (p_data->>'games')::integer, (p_data->>'completed')::integer, (p_data->>'seconds')::integer)
            end;
            if d.last_notice_at > moment - interval '2 seconds' and kind not in ('victory','summary') then
                return jsonb_build_object('error','rate_limited');
            end if;
            if message is not null then
                insert into public.telegram_notices(owner,binding,event_key,message)
                    values(p_owner,d.binding,event_key,message) on conflict do nothing;
                update public.telegram_devices set last_notice_at=moment where owner=p_owner;
            end if;
        end if;
    else null;
    end case;
    return jsonb_build_object(
        'state', case when d.binding is not null then 'connected'
            when d.link_hash is not null and d.expires_at > moment then 'pending' else 'disconnected' end,
        'name', d.account_name, 'binding', d.binding, 'events', d.events, 'expires_at', d.expires_at);
end $$;

create function public.telegram_confirm(p_hash text, p_chat bigint, p_name text)
returns uuid language plpgsql set search_path = '' as $$
declare d public.telegram_devices;
begin
    update public.telegram_devices set chat_id=p_chat, account_name=left(p_name, 160),
        binding=gen_random_uuid(), link_hash=null, expires_at=null, heartbeat_at=clock_timestamp(),
        offline_reported=false
        where link_hash=p_hash and expires_at > clock_timestamp() and binding is null
        returning * into d;
    if not found then return null; end if;
    insert into public.telegram_notices(owner,binding,event_key,message)
        values(d.owner,d.binding,'linked','✅ Telegram успешно привязан!');
    return d.owner;
end $$;

create function public.telegram_sweep()
returns void language plpgsql set search_path = '' as $$
begin
    with offline as (
        update public.telegram_devices set offline_reported=true
        where binding is not null and 'offline'=any(events) and not offline_reported
            and heartbeat_at < now() - interval '5 minutes'
        returning owner,binding
    )
    insert into public.telegram_notices(owner,binding,event_key,message)
        select owner,binding,gen_random_uuid()::text,'📡 Shadow AFK перестал выходить на связь' from offline;
    update public.telegram_devices set link_hash=null, expires_at=null where expires_at <= now();
    delete from public.telegram_notices where created_at < now() - interval '30 days';
end $$;

create function public.telegram_claim(p_owner uuid, p_limit integer)
returns table(id bigint, chat_id bigint, message text) language sql set search_path = '' as $$
    with picked as (
        select n.id, d.chat_id from public.telegram_notices n
        join public.telegram_devices d on d.owner=n.owner and d.binding=n.binding
        where n.claimed_at is null and (p_owner is null or n.owner=p_owner)
        order by n.id limit least(p_limit,100) for update of n skip locked
    )
    update public.telegram_notices n set claimed_at=now()
    from picked p where n.id=p.id returning n.id,p.chat_id,n.message;
$$;

revoke execute on function public.telegram_device(uuid,text,jsonb), public.telegram_confirm(text,bigint,text),
    public.telegram_sweep(), public.telegram_claim(uuid,integer) from public, anon, authenticated;
grant execute on function public.telegram_device(uuid,text,jsonb), public.telegram_confirm(text,bigint,text),
    public.telegram_sweep(), public.telegram_claim(uuid,integer) to service_role;
