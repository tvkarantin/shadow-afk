begin;
insert into auth.users(id) values ('a0000000-0000-0000-0000-000000000001'), ('b0000000-0000-0000-0000-000000000002');
do $$
declare
    a uuid := 'a0000000-0000-0000-0000-000000000001';
    b uuid := 'b0000000-0000-0000-0000-000000000002';
begin
    assert public.telegram_begin(a,'login-unknown','login')->>'state' = 'pending';
    assert public.telegram_confirm('login-unknown',101,'Alice') is null;
    assert public.telegram_device(a,'status','{}')->>'state' = 'disconnected';
    update public.telegram_devices set last_link_at=null where owner=a;
    assert public.telegram_begin(a,'register','register')->>'state' = 'pending';
    assert public.telegram_confirm('register',101,'Alice') = a;
    assert public.telegram_confirm('register',202,'Bob') is null;
    assert public.telegram_begin(b,'duplicate','register')->>'state' = 'pending';
    assert public.telegram_confirm('duplicate',101,'Alice') is null;
    update public.telegram_devices set last_link_at=null where owner=b;
    assert public.telegram_begin(b,'login','login')->>'state' = 'pending';
    assert public.telegram_confirm('login',101,'Alice') = b;
    assert public.telegram_device(b,'status','{}')->>'name' = 'Alice';
    assert not has_function_privilege('authenticated','public.telegram_begin(uuid,text,text)','execute');
    assert not has_table_privilege('authenticated','public.telegram_accounts','select');
end $$;
rollback;
