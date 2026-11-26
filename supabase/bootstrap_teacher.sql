-- Run once in the Supabase SQL Editor AFTER creating the first teacher in
-- Authentication -> Users. Use the real teacher email/name below. No passwords.
-- This is an administrator operation, never callable from the application.
do $$
declare
  admin_email text := 'REPLACE_WITH_TEACHER_EMAIL';
  admin_name text := 'REPLACE_WITH_TEACHER_NAME';
  auth_id uuid;
begin
  if admin_email = 'REPLACE_WITH_TEACHER_EMAIL' or admin_name = 'REPLACE_WITH_TEACHER_NAME' then
    raise exception 'Edit admin_email and admin_name before running this script';
  end if;
  select id into auth_id from auth.users
    where lower(email) = lower(btrim(admin_email)) and email_confirmed_at is not null;
  if auth_id is null then
    raise exception 'Create and confirm the teacher Auth user first';
  end if;
  if exists(select from public.profiles where id=auth_id and role <> 'teacher') then
    raise exception 'This email already belongs to a student. Use a separate staff account';
  end if;
  insert into public.profiles(id,role,display_name)
    values(auth_id,'teacher',btrim(admin_name)) on conflict(id) do nothing;
end;
$$;
