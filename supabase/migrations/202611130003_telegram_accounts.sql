create table public.telegram_accounts (
    chat_id bigint primary key,
    created_at timestamptz not null default now()
);
alter table public.telegram_accounts enable row level security;
revoke all on public.telegram_accounts from public, anon, authenticated;
insert into public.telegram_accounts(chat_id)
    select distinct chat_id from public.telegram_devices where chat_id is not null;

alter table public.telegram_devices add column link_intent text not null default 'either'
    check (link_intent in ('either','register','login'));

create function public.telegram_begin(p_owner uuid,p_hash text,p_intent text)
returns jsonb language plpgsql set search_path = '' as $$
declare result jsonb;
begin
    result := public.telegram_device(p_owner,'begin',jsonb_build_object('hash',p_hash));
    if result->>'state' = 'pending' then
        update public.telegram_devices set link_intent=p_intent where owner=p_owner;
    end if;
    return result;
end $$;

create or replace function public.telegram_confirm(p_hash text,p_chat bigint,p_name text)
returns uuid language plpgsql set search_path = '' as $$
declare
    d public.telegram_devices;
    account_exists boolean;
    rejection text;
begin
    perform pg_advisory_xact_lock(p_chat);
    select * into d from public.telegram_devices
        where link_hash=p_hash and expires_at > clock_timestamp() and binding is null for update;
    if not found then return null; end if;
    select exists(select from public.telegram_accounts where chat_id=p_chat) into account_exists;
    if d.link_intent='register' and account_exists then
        rejection := 'account_exists';
    elsif d.link_intent='login' and not account_exists then
        rejection := 'account_missing';
    end if;
    if rejection is not null then
        update public.telegram_devices set link_hash=null, expires_at=null where owner=d.owner;
        return null;
    end if;
    insert into public.telegram_accounts(chat_id) values(p_chat) on conflict do nothing;
    update public.telegram_devices set chat_id=p_chat, account_name=left(p_name,160),
        binding=gen_random_uuid(), link_hash=null, expires_at=null, heartbeat_at=clock_timestamp(),
        offline_reported=false where owner=d.owner returning * into d;
    insert into public.telegram_notices(owner,binding,event_key,message)
        values(d.owner,d.binding,'linked','✅ Telegram успешно привязан!');
    return d.owner;
end $$;

revoke execute on function public.telegram_begin(uuid,text,text) from public, anon, authenticated;
grant execute on function public.telegram_begin(uuid,text,text) to service_role;
