-- Run as postgres against a test database with the Telegram migration applied.
begin;
insert into auth.users(id) values ('a0000000-0000-0000-0000-000000000001'), ('b0000000-0000-0000-0000-000000000002');

do $$
declare
    a uuid := 'a0000000-0000-0000-0000-000000000001';
    b uuid := 'b0000000-0000-0000-0000-000000000002';
    a_binding text;
    b_binding text;
    data jsonb;
begin
    assert public.telegram_device(a,'begin','{"hash":"hash-a"}')->>'state' = 'pending';
    assert public.telegram_device(b,'begin','{"hash":"hash-b"}')->>'state' = 'pending';
    assert public.telegram_confirm('hash-a',101,'Alice') = a;
    assert public.telegram_confirm('hash-b',202,'Bob') = b;
    assert public.telegram_confirm('hash-a',202,'Bob') is null;
    assert (select count(*) from public.telegram_claim(a,20) where chat_id=101) = 1;
    assert (select count(*) from public.telegram_claim(b,20) where chat_id=202) = 1;
    assert (select count(*) from public.telegram_claim(null,20)) = 0;
    a_binding := public.telegram_device(a,'status','{}')->>'binding';
    b_binding := public.telegram_device(b,'status','{}')->>'binding';
    assert public.telegram_device(a,'status','{}')->>'name' = 'Alice';
    assert public.telegram_device(b,'status','{}')->>'name' = 'Bob';
    data := jsonb_build_object('binding',b_binding,'event','victory','key','match-1','chat_id',202);
    assert public.telegram_device(a,'notify',data)->>'error' = 'not_linked';
    data := jsonb_set(data,'{binding}',to_jsonb(a_binding));
    perform public.telegram_device(a,'notify',data);
    perform public.telegram_device(a,'notify',data);
    assert (select count(*) from public.telegram_claim(a,20) where chat_id=101 and message like '🏆%') = 1;
    assert (select count(*) from public.telegram_claim(b,20)) = 0;

    update public.telegram_devices set heartbeat_at=now()-interval '6 minutes' where owner=a;
    perform public.telegram_sweep();
    perform public.telegram_sweep();
    assert (select count(*) from public.telegram_claim(a,20) where message like '📡%') = 1;
    assert public.telegram_device(a,'unlink','{}')->>'state' = 'disconnected';
    assert public.telegram_device(a,'notify',data)->>'error' = 'not_linked';
    assert public.telegram_device(b,'status','{}')->>'binding' = b_binding;

    update public.telegram_devices set last_link_at=null where owner=a;
    assert public.telegram_device(a,'begin','{"hash":"expired"}')->>'state' = 'pending';
    update public.telegram_devices set expires_at=now()-interval '1 second' where owner=a;
    assert public.telegram_confirm('expired',101,'Alice') is null;
    assert public.telegram_device(a,'status','{}')->>'state' = 'disconnected';
    update public.telegram_devices set last_link_at=null where owner=a;
    perform public.telegram_device(a,'begin','{"hash":"cancelled"}');
    perform public.telegram_device(a,'cancel','{}');
    assert public.telegram_confirm('cancelled',101,'Alice') is null;
    assert not has_function_privilege('authenticated','public.telegram_confirm(text,bigint,text)','execute');
    assert not has_table_privilege('authenticated','public.telegram_devices','update');
end $$;
rollback;
