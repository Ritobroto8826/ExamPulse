-- Run after the migration on a disposable PostgreSQL test database only.
-- Covers actual SQL permissions/policies, not application-side simulations.
\set ON_ERROR_STOP on
begin;
do $$ begin
  if current_database() not like '%test%' then raise exception 'Use a disposable test database'; end if;
end $$;
create function public.test_assert(value boolean, message text) returns void
language plpgsql as $$ begin if not coalesce(value,false) then raise exception 'TEST FAILED: %',message; end if; end $$;
grant execute on function public.test_assert(boolean,text) to authenticated,anon,service_role;

select public.test_assert((select count(*)=2 from public.subjects), 'exactly 2 subjects');
select public.test_assert((select count(*)=27 from public.topics), 'exactly 27 chapters');
select public.test_assert((select count(*)=0 from public.students), 'no seeded students');
select public.test_assert((select count(*)=0 from public.profiles), 'no seeded accounts');
insert into auth.users(id,email) values
('00000000-0000-4000-8000-000000000001','teacher@test.example'),
('00000000-0000-4000-8000-000000000002','one@test.example'),
('00000000-0000-4000-8000-000000000003','two@test.example');
insert into public.profiles(id,role,display_name) values
('00000000-0000-4000-8000-000000000001','teacher','Test teacher');
set local role service_role;
select public.provision_student('00000000-0000-4000-8000-000000000002','Student One','Class 10','one@test.example') as one \gset
select public.provision_student('00000000-0000-4000-8000-000000000003','Student Two','Class 10','two@test.example') as two \gset
reset role;
insert into public.exams(name,exam_date) values('Policy test',current_date) returning id as exam \gset
select id as maths from public.subjects where name='Mathematics' \gset
select id as science from public.subjects where name='Science' \gset
select id as math_topic from public.topics where name='Real Numbers' \gset
select id as science_topic from public.topics where name='Electricity' \gset
insert into public.scores(student_id,exam_id,subject_id,topic_id,score) values
(:one,:exam,:maths,:math_topic,85),(:two,:exam,:maths,:math_topic,64);

-- An unverified/anonymous client has neither tables nor comparison access.
set local role anon;
do $$ begin
  begin perform * from public.scores; raise exception 'anon read allowed'; exception when insufficient_privilege then null; end;
  begin perform * from public.exam_comparison(1); raise exception 'anon comparison allowed'; exception when insufficient_privilege then null; end;
end $$;
reset role;

select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
select public.test_assert((select count(*)=1 from public.profiles), 'student sees only own profile');
select public.test_assert((select count(*)=1 from public.students), 'student sees only own roster');
select public.test_assert((select count(*)=1 from public.scores), 'raw marks protected by RLS');
select public.test_assert((select count(*)=1 from public.score_details), 'view inherits ownership RLS');
select public.test_assert((select max(score)=85 from public.score_details), 'student correct own score');
select public.test_assert((select count(*)=2 from public.exam_comparison(:exam)), 'named comparison explicitly allowed');
select public.test_assert((select count(*)=0 from public.audit_log), 'student cannot read audits');
-- No UPDATE rows are visible to the student's write policy.
with changed as (update public.scores set score=99 returning id)
 select public.test_assert((select count(*)=0 from changed), 'student cannot update marks');
do $$ begin
  begin insert into public.exams(name,exam_date) values('Forbidden',current_date); raise exception 'student exam write allowed'; exception when insufficient_privilege then null; end;
  begin update public.profiles set role='teacher'; raise exception 'role escalation allowed'; exception when insufficient_privilege then null; end;
  begin perform public.provision_student('00000000-0000-4000-8000-000000000002','x','x','x@example.com'); raise exception 'student provisioning allowed'; exception when insufficient_privilege then null; end;
  begin perform public.set_student_active(1,false); raise exception 'student access mutation allowed'; exception when insufficient_privilege then null; end;
  begin perform public.import_score_records('[]'); raise exception 'student import allowed'; exception when insufficient_privilege then null; end;
  begin perform public.claim_invitation(); raise exception 'student invite allowed'; exception when insufficient_privilege then null; end;
end $$;
reset role;

select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
select public.test_assert((select count(*)=2 from public.score_details), 'teacher reads full class');
select public.test_assert((select count(*)=2 from public.students), 'teacher reads full roster');
select public.test_assert(public.is_teacher(), 'teacher role verified from profiles');
select public.claim_invitation();
select public.set_student_active(:two,false);
select public.test_assert((select count(*)=1 from public.exam_comparison(:exam)), 'disabled accounts excluded from comparison');
-- DB constraints reject chapter/subject mismatches and invalid marks.
reset role;
do $$ declare sid bigint; eid bigint; math_id bigint; science_chapter bigint;
begin
  select id into sid from public.students limit 1;
  select id into eid from public.exams limit 1;
  select id into math_id from public.subjects where name='Mathematics';
  select id into science_chapter from public.topics where name='Electricity';
  begin insert into public.scores(student_id,exam_id,subject_id,topic_id,score)
    values(sid,eid,math_id,science_chapter,50);
    raise exception 'mismatched chapter allowed'; exception when foreign_key_violation then null; end;
  begin update public.scores set score=101; raise exception 'invalid marks allowed'; exception when check_violation then null; end;
end $$;

-- Atomic import rollback: valid first row must not survive an invalid second row.
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ declare sid bigint; tid bigint; subid bigint; payload jsonb;
begin
  select id into sid from public.students where email='one@test.example';
  select id,subject_id into tid,subid from public.topics where name='Real Numbers';
  payload := jsonb_build_array(
    jsonb_build_object('student_id',sid,'subject_id',subid,'topic_id',tid,'exam','Atomic rollback test','exam_date',current_date,'score',90),
    jsonb_build_object('student_id',sid,'subject_id',subid,'topic_id',tid,'exam','Atomic rollback test','exam_date',current_date,'score',999));
  begin perform public.import_score_records(payload); raise exception 'invalid import allowed'; exception when check_violation then null; end;
  perform public.test_assert(not exists(select from public.exams where name='Atomic rollback test'),'failed import rolled back all rows');
end $$;
select public.test_assert((select count(*)>0 from public.audit_log), 'mutations audited');
do $$ declare blocked boolean := false; begin
  -- One slot was claimed above; nineteen more fill the per-teacher hourly limit.
  for i in 1..19 loop perform public.claim_invitation(); end loop;
  begin perform public.claim_invitation(); exception when sqlstate 'P0001' then blocked := true; end;
  perform public.test_assert(blocked, 'invitation rate limit enforced atomically in database');
  begin insert into public.subjects(name,position) values('English',3);
    raise exception 'curriculum mutation allowed'; exception when insufficient_privilege then null; end;
end $$;
reset role;

-- A disabled student is denied even with an otherwise valid existing JWT.
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000003',true);
set local role authenticated;
select public.test_assert(not public.is_active(), 'inactive account blocked');
select public.test_assert((select count(*)=0 from public.scores), 'inactive cannot read scores');
select public.test_assert((select count(*)=0 from public.topics), 'inactive cannot read curriculum');
do $$ begin
  begin perform * from public.exam_comparison(1); raise exception 'inactive comparison allowed'; exception when insufficient_privilege then null; end;
end $$;
reset role;
-- Unprovisioned Auth users cannot bootstrap their own school role.
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000099',true);
set local role authenticated;
select public.test_assert(not public.is_active(), 'unprovisioned account blocked');
select public.test_assert((select count(*)=0 from public.score_details), 'unprovisioned gets no marks');
reset role;
rollback;
\echo ALL POSTGRESQL RLS TESTS PASSED
