-- TEST ONLY: emulate Supabase roles/Auth schema in a disposable local PostgreSQL.
-- Never run this bootstrap against a hosted Supabase project.
\set ON_ERROR_STOP on
DO $$ begin
  if current_database() not like '%test%' then raise exception 'Use a disposable test database'; end if;
  if not exists(select from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists(select from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists(select from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create table auth.users(id uuid primary key, email text);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid;
$$;
grant usage on schema auth to authenticated, anon, service_role;
grant execute on function auth.uid() to authenticated, anon, service_role;
