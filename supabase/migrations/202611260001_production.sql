-- ExamPulse / fresh Supabase project only. No demo people, passwords or marks.
-- Apply once with `supabase db push`, or the Supabase SQL Editor.
begin;

create table public.students (
  id bigint generated always as identity primary key,
  name text not null check (length(btrim(name)) between 1 and 120),
  batch text not null check (length(btrim(batch)) between 1 and 80),
  email text not null check (email = lower(btrim(email)) and length(email) between 3 and 254),
  joined_date date not null default current_date,
  unique(email)
);
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('teacher', 'student')),
  display_name text not null check (length(btrim(display_name)) between 1 and 120),
  student_id bigint unique references public.students(id),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  check ((role = 'teacher' and student_id is null) or (role = 'student' and student_id is not null))
);
create table public.subjects (
  id bigint generated always as identity primary key,
  name text not null unique check (name in ('Mathematics', 'Science')),
  position integer not null unique
);
create table public.topics (
  id bigint generated always as identity primary key,
  subject_id bigint not null references public.subjects(id),
  name text not null,
  position integer not null check (position between 1 and 14),
  unique(subject_id, name), unique(subject_id, position), unique(id, subject_id)
);
create table public.exams (
  id bigint generated always as identity primary key,
  name text not null check (length(btrim(name)) between 1 and 160),
  exam_date date not null,
  kind text not null default 'Weekly Test',
  unique(name, exam_date)
);
create table public.scores (
  id bigint generated always as identity primary key,
  student_id bigint not null references public.students(id),
  exam_id bigint not null references public.exams(id),
  subject_id bigint not null references public.subjects(id),
  topic_id bigint not null,
  score numeric(5,2) not null check (score between 0 and 100),
  max_score numeric(5,2) not null default 100 check (max_score = 100),
  created_at timestamptz not null default now(),
  foreign key (topic_id, subject_id) references public.topics(id, subject_id),
  unique(student_id, exam_id, topic_id)
);
create index scores_exam on public.scores(exam_id);
create index scores_student_date on public.scores(student_id, exam_id);
create table public.upcoming_tests (
  id bigint generated always as identity primary key,
  title text not null check (length(btrim(title)) between 1 and 160),
  subject_id bigint references public.subjects(id),
  test_date date not null,
  topic text check (topic is null or length(topic) <= 240),
  notes text not null default '' check (length(notes) <= 1000),
  created_at timestamptz not null default now(),
  check (subject_id is not null or topic is null),
  foreign key (subject_id, topic) references public.topics(subject_id, name)
);
create index upcoming_tests_date on public.upcoming_tests(test_date);
create table public.audit_log (
  id bigint generated always as identity primary key,
  actor uuid,
  action text not null,
  entity text not null,
  entity_id text,
  before_data jsonb,
  after_data jsonb,
  created_at timestamptz not null default now()
);
create table public.invitation_requests (
  id bigint generated always as identity primary key,
  teacher_id uuid not null references public.profiles(id),
  created_at timestamptz not null default now()
);
create index invitation_rate on public.invitation_requests(teacher_id, created_at);

-- SECURITY DEFINER helpers read protected profiles without RLS recursion.
create function public.is_active() returns boolean language sql stable security definer
set search_path = '' as $$
  select exists(select 1 from public.profiles where id = auth.uid() and active);
$$;
create function public.is_teacher() returns boolean language sql stable security definer
set search_path = '' as $$
  select exists(select 1 from public.profiles where id = auth.uid() and role = 'teacher' and active);
$$;
create function public.current_student_id() returns bigint language sql stable security definer
set search_path = '' as $$
  select student_id from public.profiles where id = auth.uid() and role = 'student' and active;
$$;

alter table public.profiles enable row level security;
alter table public.students enable row level security;
alter table public.subjects enable row level security;
alter table public.topics enable row level security;
alter table public.exams enable row level security;
alter table public.scores enable row level security;
alter table public.upcoming_tests enable row level security;
alter table public.audit_log enable row level security;
alter table public.invitation_requests enable row level security;

create policy profiles_read on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_teacher());
-- No API profile INSERT/UPDATE: users cannot promote themselves or change links.
create policy students_read on public.students for select to authenticated
  using (public.is_teacher() or id = public.current_student_id());
create policy students_update on public.students for update to authenticated
  using (public.is_teacher()) with check (public.is_teacher());
create policy subjects_read on public.subjects for select to authenticated using (public.is_active());
create policy topics_read on public.topics for select to authenticated using (public.is_active());
create policy exams_read on public.exams for select to authenticated using (public.is_active());
create policy exams_write on public.exams for all to authenticated
  using (public.is_teacher()) with check (public.is_teacher());
create policy scores_read on public.scores for select to authenticated
  using (public.is_teacher() or student_id = public.current_student_id());
create policy scores_write on public.scores for all to authenticated
  using (public.is_teacher()) with check (public.is_teacher());
create policy upcoming_read on public.upcoming_tests for select to authenticated using (public.is_active());
create policy upcoming_write on public.upcoming_tests for all to authenticated
  using (public.is_teacher()) with check (public.is_teacher());
create policy audit_read on public.audit_log for select to authenticated using (public.is_teacher());
create policy invite_read on public.invitation_requests for select to authenticated using (public.is_teacher());

create view public.score_details with (security_invoker = true) as
select s.id as score_id, s.student_id, st.name as student_name, st.batch,
       e.id as exam_id, e.name as exam_name, e.exam_date, e.kind as exam_kind,
       sub.id as subject_id, sub.name as subject, t.id as topic_id, t.name as topic,
       s.score, s.max_score
from public.scores s
join public.students st on st.id = s.student_id
join public.exams e on e.id = s.exam_id
join public.subjects sub on sub.id = s.subject_id
join public.topics t on t.id = s.topic_id;
create view public.schedule_details with (security_invoker = true) as
select u.*, s.name as subject from public.upcoming_tests u
left join public.subjects s on s.id = u.subject_id;
create view public.student_access with (security_invoker = true) as
select s.id, s.name, s.batch, s.email, s.joined_date, p.active
from public.students s join public.profiles p on p.student_id = s.id;

-- Intentional sharing exception requested by the owner: named exam summaries.
-- No email, Auth UUID, password data, tokens, or unrestricted raw score records.
create function public.exam_comparison(p_exam_id bigint, p_subject_id bigint default null,
                                       p_topic_id bigint default null)
returns table(student_id bigint, student_name text, batch text, score numeric, topic_count bigint)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_active() then raise insufficient_privilege using message = 'Not authorized'; end if;
  return query
  select st.id, st.name, st.batch, m.mark, coalesce(m.n, 0::bigint)
  from public.students st
  join public.profiles p on p.student_id = st.id and p.active
  left join (
    select s.student_id as sid, avg(s.score) as mark, count(distinct s.topic_id) as n
    from public.scores s where s.exam_id = p_exam_id
      and (p_subject_id is null or s.subject_id = p_subject_id)
      and (p_topic_id is null or s.topic_id = p_topic_id)
    group by s.student_id
  ) m on m.sid = st.id
  order by m.mark desc nulls last, st.name, st.id;
end;
$$;

-- Auth users are created by an Edge Function. Only its service role can link
-- them to a roster row. One DB transaction prevents half-created student links.
create function public.provision_student(p_user_id uuid, p_name text, p_batch text, p_email text)
returns bigint language plpgsql security definer set search_path = '' as $$
declare sid bigint;
begin
  insert into public.students(name, batch, email)
    values(btrim(p_name), btrim(p_batch), lower(btrim(p_email))) returning id into sid;
  insert into public.profiles(id, role, display_name, student_id)
    values(p_user_id, 'student', btrim(p_name), sid);
  return sid;
end;
$$;

create function public.claim_invitation() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_teacher() then raise insufficient_privilege using message = 'Not authorized'; end if;
  perform pg_advisory_xact_lock(hashtextextended('invite:' || auth.uid()::text, 0));
  if (select count(*) from public.invitation_requests
      where teacher_id = auth.uid() and created_at > now() - interval '1 hour') >= 20 then
    raise exception 'Invitation limit reached' using errcode = 'P0001';
  end if;
  insert into public.invitation_requests(teacher_id) values(auth.uid());
end;
$$;

create function public.set_student_active(p_student_id bigint, p_active boolean) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_teacher() then raise insufficient_privilege using message = 'Not authorized'; end if;
  update public.profiles set active = p_active where student_id = p_student_id and role = 'student';
  if not found then raise exception 'Student not found'; end if;
end;
$$;

-- Whole validated file imports in ONE transaction; any error rolls back all rows.
create function public.import_score_records(p_records jsonb) returns integer
language plpgsql security definer set search_path = '' as $$
declare r jsonb; eid bigint; n integer := 0;
begin
  if not public.is_teacher() then raise insufficient_privilege using message = 'Not authorized'; end if;
  if jsonb_typeof(p_records) <> 'array' or jsonb_array_length(p_records) not between 1 and 1000 then
    raise exception 'Provide between 1 and 1000 rows';
  end if;
  for r in select value from jsonb_array_elements(p_records) loop
    insert into public.exams(name, exam_date, kind)
      values(btrim(r->>'exam'), (r->>'exam_date')::date, coalesce(nullif(r->>'exam_kind', ''), 'Practice Test'))
      on conflict(name, exam_date) do update set name = excluded.name returning id into eid;
    insert into public.scores(student_id, exam_id, subject_id, topic_id, score)
      values((r->>'student_id')::bigint, eid, (r->>'subject_id')::bigint,
             (r->>'topic_id')::bigint, (r->>'score')::numeric)
      on conflict(student_id, exam_id, topic_id) do update set score = excluded.score;
    n := n + 1;
  end loop;
  return n;
end;
$$;

create function public.audit_change() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_log(actor, action, entity, entity_id, before_data, after_data)
  values(auth.uid(), tg_op, tg_table_name,
         case when tg_op = 'DELETE' then old.id::text else new.id::text end,
         case when tg_op <> 'INSERT' then to_jsonb(old) end,
         case when tg_op <> 'DELETE' then to_jsonb(new) end);
  return null;
end;
$$;
create trigger audit_scores after insert or update or delete on public.scores
  for each row execute function public.audit_change();
create trigger audit_roster after insert or update or delete on public.students
  for each row execute function public.audit_change();
create trigger audit_profiles after insert or update or delete on public.profiles
  for each row execute function public.audit_change();
create trigger audit_schedule after insert or update or delete on public.upcoming_tests
  for each row execute function public.audit_change();

-- Lock down grants explicitly; RLS is enforced on every user-scoped REST call.
revoke create on schema public from public, anon, authenticated;
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
grant usage on schema public to authenticated, service_role;
grant select on public.profiles, public.students, public.subjects, public.topics,
  public.exams, public.scores, public.upcoming_tests, public.audit_log,
  public.invitation_requests, public.score_details, public.schedule_details,
  public.student_access to authenticated;
grant insert, update, delete on public.exams, public.scores, public.upcoming_tests to authenticated;
grant update(name, batch) on public.students to authenticated;
grant usage, select on all sequences in schema public to authenticated;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;

revoke execute on function public.is_active(), public.is_teacher(), public.current_student_id(),
  public.exam_comparison(bigint,bigint,bigint), public.provision_student(uuid,text,text,text),
  public.claim_invitation(), public.set_student_active(bigint,boolean),
  public.import_score_records(jsonb), public.audit_change() from public, anon, authenticated;
grant execute on function public.is_active(), public.is_teacher(), public.current_student_id(),
  public.exam_comparison(bigint,bigint,bigint), public.claim_invitation(),
  public.set_student_active(bigint,boolean), public.import_score_records(jsonb) to authenticated;
grant execute on function public.provision_student(uuid,text,text,text) to service_role;

-- Curriculum seed appended below. No automatic user/profile creation trigger.
insert into public.subjects(name,position) values('Mathematics',1);
insert into public.topics(subject_id,name,position) select id,'Real Numbers',1 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Polynomials',2 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Pair of Linear Equations in Two Variables',3 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Quadratic Equations',4 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Arithmetic Progressions',5 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Triangles',6 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Coordinate Geometry',7 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Introduction to Trigonometry',8 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Some Applications of Trigonometry',9 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Circles',10 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Areas Related to Circles',11 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Surface Areas and Volumes',12 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Statistics',13 from public.subjects where name='Mathematics';
insert into public.topics(subject_id,name,position) select id,'Probability',14 from public.subjects where name='Mathematics';
insert into public.subjects(name,position) values('Science',2);
insert into public.topics(subject_id,name,position) select id,'Chemical Reactions and Equations',1 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Acids, Bases and Salts',2 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Metals and Non-metals',3 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Carbon and its Compounds',4 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Life Processes',5 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Control and Coordination',6 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'How do Organisms Reproduce?',7 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Heredity',8 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Light – Reflection and Refraction',9 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'The Human Eye and the Colourful World',10 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Electricity',11 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Magnetic Effects of Electric Current',12 from public.subjects where name='Science';
insert into public.topics(subject_id,name,position) select id,'Our Environment',13 from public.subjects where name='Science';

commit;
