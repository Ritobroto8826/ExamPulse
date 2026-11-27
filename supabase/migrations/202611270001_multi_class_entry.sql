-- ExamPulse multi-class entry upgrade: per-class curricula (8/9/10),
-- multi-topic saves with raw-mark conversion, and class-matched score checks.
-- Runs on a fresh project directly after 202611260001_production.sql, and on
-- an existing deployment of that migration. No rows are deleted.
begin;

-- ---------------------------------------------------------------------------
-- 1) Students carry an explicit class level. Existing rows are parsed from
--    their batch text where possible; unrecognised text falls back to Class 10
--    and should be reviewed after upgrading (Manage Students can fix it).
-- ---------------------------------------------------------------------------
alter table public.students add column class_level smallint;
update public.students
   set class_level = (substring(batch from '(?i)class *([0-9]{1,2})'))::smallint
 where class_level is null and batch ~* 'class *[0-9]{1,2}';
update public.students set class_level = 10 where class_level is null;
alter table public.students alter column class_level set not null;
alter table public.students
  add constraint students_class_level_check check (class_level between 1 and 12);
grant update(class_level) on public.students to authenticated;

-- ---------------------------------------------------------------------------
-- 2) Drop the schedule FK before the topic name/position uniqueness rules it
--    depends on are replaced.
-- ---------------------------------------------------------------------------
alter table public.upcoming_tests add column class_level smallint;
alter table public.upcoming_tests drop constraint upcoming_tests_subject_id_topic_fkey;

-- ---------------------------------------------------------------------------
-- 3) Topics gain a class dimension; existing rows become Class 10.
-- ---------------------------------------------------------------------------
alter table public.topics add column class_level smallint;
update public.topics set class_level = 10 where class_level is null;
alter table public.topics alter column class_level set not null;
alter table public.topics
  add constraint topics_class_level_check check (class_level between 1 and 12);
-- Class 8 Mathematics has 16 chapters; widen the old 1..14 position range.
alter table public.topics drop constraint topics_position_check;
alter table public.topics
  add constraint topics_position_check check (position between 1 and 40);
alter table public.topics drop constraint topics_subject_id_name_key;
alter table public.topics drop constraint topics_subject_id_position_key;
alter table public.topics
  add constraint topics_subject_id_class_name_key unique (subject_id, class_level, name);
alter table public.topics
  add constraint topics_subject_id_class_position_key unique (subject_id, class_level, position);

-- Existing scheduled chapters were written against the pre-upgrade Class 10
-- curriculum: carry that class across before the not-null check below.
update public.upcoming_tests u
   set class_level = t.class_level
  from public.topics t
 where u.class_level is null and u.topic is not null
   and t.subject_id = u.subject_id and t.name = u.topic;
update public.upcoming_tests
   set class_level = 10
 where class_level is null and topic is not null;

-- A scheduled chapter must name the class whose curriculum it belongs to.
alter table public.upcoming_tests
  add constraint upcoming_tests_subject_class_topic_fkey
  foreign key (subject_id, class_level, topic)
  references public.topics(subject_id, class_level, name);
alter table public.upcoming_tests
  add constraint upcoming_tests_topic_class_check
  check (topic is null or class_level is not null);

-- ---------------------------------------------------------------------------
-- 4) Scores keep the derived 0-100 percentage and may also record the raw
--    marks the teacher typed (e.g. 15 out of 20 -> 75.00).
-- ---------------------------------------------------------------------------
alter table public.scores
  add column raw_score numeric(6,2),
  add column raw_max numeric(6,2),
  add constraint scores_raw_marks_check check (
    (raw_score is null) = (raw_max is null)
    and (raw_score is null or (raw_score >= 0 and raw_max > 0 and raw_score <= raw_max))
  );

-- ---------------------------------------------------------------------------
-- 5) A score's chapter must belong to the student's class, even when written
--    through the API rather than the UI. Runs for UI writes and imports alike;
--    students cannot write scores at all (RLS), so only teachers/imports fire it.
-- ---------------------------------------------------------------------------
create function public.check_score_class() returns trigger
language plpgsql as $$
declare v_student_class smallint; v_topic_class smallint;
begin
  select class_level into v_student_class
    from public.students where id = new.student_id;
  select class_level into v_topic_class
    from public.topics where id = new.topic_id;
  if v_student_class is distinct from v_topic_class then
    raise exception 'Score chapter does not match the student''s class'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;
create trigger scores_class_match before insert or update of student_id, topic_id
  on public.scores for each row execute function public.check_score_class();
revoke execute on function public.check_score_class() from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 6) Reporting views expose the class level and raw marks.
-- ---------------------------------------------------------------------------
drop view public.score_details;
create view public.score_details with (security_invoker = true) as
select s.id as score_id, s.student_id, st.name as student_name, st.batch,
       st.class_level,
       e.id as exam_id, e.name as exam_name, e.exam_date, e.kind as exam_kind,
       sub.id as subject_id, sub.name as subject, t.id as topic_id, t.name as topic,
       s.score, s.max_score, s.raw_score, s.raw_max
from public.scores s
join public.students st on st.id = s.student_id
join public.exams e on e.id = s.exam_id
join public.subjects sub on sub.id = s.subject_id
join public.topics t on t.id = s.topic_id;
grant select on public.score_details to authenticated;

drop view public.student_access;
create view public.student_access with (security_invoker = true) as
select s.id, s.name, s.batch, s.class_level, s.email, s.joined_date, p.active
from public.students s join public.profiles p on p.student_id = s.id;
grant select on public.student_access to authenticated;

-- ---------------------------------------------------------------------------
-- 7) Provisioning now takes the student's class. The Edge Function is updated
--    to match; redeploy it together with this migration.
-- ---------------------------------------------------------------------------
drop function public.provision_student(uuid, text, text, text);
create function public.provision_student(p_user_id uuid, p_name text, p_batch text,
                                         p_email text, p_class_level integer)
returns bigint language plpgsql security definer set search_path = '' as $$
declare sid bigint;
begin
  insert into public.students(name, batch, email, class_level)
    values(btrim(p_name), btrim(p_batch), lower(btrim(p_email)), p_class_level)
    returning id into sid;
  insert into public.profiles(id, role, display_name, student_id)
    values(p_user_id, 'student', btrim(p_name), sid);
  return sid;
end;
$$;
revoke execute on function public.provision_student(uuid, text, text, text, integer)
  from public, anon, authenticated;
grant execute on function public.provision_student(uuid, text, text, text, integer)
  to service_role;

-- ---------------------------------------------------------------------------
-- 8) Peer comparison stays an explicit sharing exception, but students only
--    ever see their own class's roster rows for an exam.
-- ---------------------------------------------------------------------------
drop function public.exam_comparison(bigint, bigint, bigint);
create function public.exam_comparison(p_exam_id bigint, p_subject_id bigint default null,
                                       p_topic_id bigint default null)
returns table(student_id bigint, student_name text, batch text, score numeric, topic_count bigint)
language plpgsql stable security definer set search_path = '' as $$
declare v_class smallint;
begin
  if not public.is_active() then raise insufficient_privilege using message = 'Not authorized'; end if;
  if not public.is_teacher() then
    select s.class_level into v_class
      from public.students s where s.id = public.current_student_id();
  end if;
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
  where v_class is null or st.class_level = v_class
  order by m.mark desc nulls last, st.name, st.id;
end;
$$;
revoke execute on function public.exam_comparison(bigint, bigint, bigint)
  from public, anon, authenticated;
grant execute on function public.exam_comparison(bigint, bigint, bigint) to authenticated;

-- ---------------------------------------------------------------------------
-- 9) Bulk import (also used by the multi-topic score form) carries the raw
--    marks alongside the derived percentage. Same signature and grants.
-- ---------------------------------------------------------------------------
create or replace function public.import_score_records(p_records jsonb) returns integer
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
    insert into public.scores(student_id, exam_id, subject_id, topic_id, score, raw_score, raw_max)
      values((r->>'student_id')::bigint, eid, (r->>'subject_id')::bigint,
             (r->>'topic_id')::bigint, (r->>'score')::numeric,
             (r->>'raw_score')::numeric, (r->>'raw_max')::numeric)
      on conflict(student_id, exam_id, topic_id)
      do update set score = excluded.score,
                    raw_score = excluded.raw_score, raw_max = excluded.raw_max;
    n := n + 1;
  end loop;
  return n;
end;
$$;
revoke execute on function public.import_score_records(jsonb) from public, anon, authenticated;
grant execute on function public.import_score_records(jsonb) to authenticated;

-- ---------------------------------------------------------------------------
-- 10) Curriculum seed for the additional classes. Generated to match
--     curriculum.py exactly (enforced by the Python test suite).
-- ---------------------------------------------------------------------------
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Rational Numbers', 1 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Linear Equations in One Variable', 2 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Understanding Quadrilaterals', 3 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Practical Geometry', 4 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Data Handling', 5 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Squares and Square Roots', 6 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Cubes and Cube Roots', 7 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Comparing Quantities', 8 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Algebraic Expressions and Identities', 9 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Visualising Solid Shapes', 10 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Mensuration', 11 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Exponents and Powers', 12 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Direct and Inverse Proportions', 13 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Factorisation', 14 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Introduction to Graphs', 15 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Playing with Numbers', 16 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Crop Production and Management', 1 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Microorganisms: Friend and Foe', 2 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Coal and Petroleum', 3 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Combustion and Flame', 4 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Conservation of Plants and Animals', 5 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Reproduction in Animals', 6 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Reaching the Age of Adolescence', 7 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Force and Pressure', 8 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Friction', 9 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Sound', 10 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Chemical Effects of Electric Current', 11 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Some Natural Phenomena', 12 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Light', 13 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Stars and the Solar System', 14 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 8, 'Pollution of Air and Water', 15 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Number Systems', 1 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Polynomials', 2 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Coordinate Geometry', 3 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Linear Equations in Two Variables', 4 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Introduction to Euclid''s Geometry', 5 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Lines and Angles', 6 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Triangles', 7 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Quadrilaterals', 8 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Areas of Parallelograms and Triangles', 9 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Circles', 10 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Constructions', 11 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Heron''s Formula', 12 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Surface Areas and Volumes', 13 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Statistics', 14 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Probability', 15 from public.subjects where name='Mathematics';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Matter in Our Surroundings', 1 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Is Matter Around Us Pure?', 2 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Atoms and Molecules', 3 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Structure of the Atom', 4 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'The Fundamental Unit of Life', 5 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Tissues', 6 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Motion', 7 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Force and Laws of Motion', 8 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Gravitation', 9 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Work and Energy', 10 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Sound', 11 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Why Do We Fall Ill?', 12 from public.subjects where name='Science';
insert into public.topics(subject_id, class_level, name, position)
  select id, 9, 'Improvement in Food Resources', 13 from public.subjects where name='Science';

commit;
