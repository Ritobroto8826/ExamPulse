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
select public.test_assert((select count(*)=86 from public.topics), '86 chapters across classes 8/9/10');
select public.test_assert((select count(*)=27 from public.topics where class_level=10), 'class 10 keeps 27 chapters');
select public.test_assert((select count(*)=0 from public.students), 'no seeded students');
select public.test_assert((select count(*)=0 from public.profiles), 'no seeded accounts');
insert into auth.users(id,email) values
('00000000-0000-4000-8000-000000000001','teacher@test.example'),
('00000000-0000-4000-8000-000000000002','one@test.example'),
('00000000-0000-4000-8000-000000000003','two@test.example'),
('00000000-0000-4000-8000-000000000004','three@test.example');
insert into public.profiles(id,role,display_name) values
('00000000-0000-4000-8000-000000000001','teacher','Test teacher');
set local role service_role;
select public.provision_student('00000000-0000-4000-8000-000000000002','Student One','Class 10','one@test.example',10) as one \gset
select public.provision_student('00000000-0000-4000-8000-000000000003','Student Two','Class 10','two@test.example',10) as two \gset
select public.provision_student('00000000-0000-4000-8000-000000000004','Student Three','Class 9','three@test.example',9) as three \gset
reset role;
insert into public.exams(name,exam_date) values('Policy test',current_date) returning id as exam \gset
select id as maths from public.subjects where name='Mathematics' \gset
select id as science from public.subjects where name='Science' \gset
select id as math_topic from public.topics where name='Real Numbers' and class_level=10 \gset
select id as science_topic from public.topics where name='Electricity' and class_level=10 \gset
select id as nine_topic from public.topics where name='Number Systems' and class_level=9 \gset
insert into public.scores(student_id,exam_id,subject_id,topic_id,score) values
(:one,:exam,:maths,:math_topic,85),(:two,:exam,:maths,:math_topic,64),
(:three,:exam,:maths,:nine_topic,77);

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
select public.test_assert((select count(*)=2 from public.exam_comparison(:exam)),
  'named comparison allowed and scoped to the student''s own class');
select public.test_assert((select count(*)=0 from public.audit_log), 'student cannot read audits');
-- No UPDATE rows are visible to the student's write policy.
with changed as (update public.scores set score=99 returning id)
 select public.test_assert((select count(*)=0 from changed), 'student cannot update marks');
do $$ begin
  begin insert into public.exams(name,exam_date) values('Forbidden',current_date); raise exception 'student exam write allowed'; exception when insufficient_privilege then null; end;
  begin update public.profiles set role='teacher'; raise exception 'role escalation allowed'; exception when insufficient_privilege then null; end;
  begin perform public.provision_student('00000000-0000-4000-8000-000000000002','x','x','x@example.com',10); raise exception 'student provisioning allowed'; exception when insufficient_privilege then null; end;
  begin perform public.set_student_active(1,false); raise exception 'student access mutation allowed'; exception when insufficient_privilege then null; end;
  begin perform public.import_score_records('[]'); raise exception 'student import allowed'; exception when insufficient_privilege then null; end;
  begin perform public.claim_invitation(); raise exception 'student invite allowed'; exception when insufficient_privilege then null; end;
  begin perform public.delete_exam((select id from public.exams where name='Policy test'), false); raise exception 'student exam delete allowed'; exception when insufficient_privilege then null; end;
end $$;
reset role;

select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
select public.test_assert((select count(*)=3 from public.score_details), 'teacher reads full class');
select public.test_assert((select count(*)=3 from public.students), 'teacher reads full roster');
select public.test_assert(public.is_teacher(), 'teacher role verified from profiles');
select public.claim_invitation();
select public.set_student_active(:two,false);
select public.test_assert((select count(*)=2 from public.exam_comparison(:exam)), 'disabled accounts excluded from comparison');
-- DB constraints reject chapter/subject mismatches and invalid marks.
reset role;
do $$ declare sid bigint; eid bigint; math_id bigint; science_chapter bigint;
  class8_chapter bigint; math_topic bigint; nine_topic bigint;
begin
  select id into sid from public.students order by id limit 1; -- Student One, Class 10
  select id into eid from public.exams limit 1;
  select id into math_id from public.subjects where name='Mathematics';
  select id into science_chapter from public.topics where name='Electricity' and class_level=10;
  select id into class8_chapter from public.topics where name='Rational Numbers' and class_level=8;
  select id into math_topic from public.topics where name='Real Numbers' and class_level=10;
  select id into nine_topic from public.topics where name='Number Systems' and class_level=9;
  begin insert into public.scores(student_id,exam_id,subject_id,topic_id,score)
    values(sid,eid,math_id,science_chapter,50);
    raise exception 'mismatched chapter allowed'; exception when foreign_key_violation then null; end;
  -- The chapter must belong to the student's class, not merely the subject.
  begin insert into public.scores(student_id,exam_id,subject_id,topic_id,score)
    values(sid,eid,math_id,class8_chapter,50);
    raise exception 'cross-class chapter allowed'; exception when check_violation then null; end;
  begin insert into public.scores(student_id,exam_id,subject_id,topic_id,score,raw_score,raw_max)
    values(sid,eid,math_id,math_topic,50,15,10);
    raise exception 'raw marks above total allowed'; exception when check_violation then null; end;
  begin update public.scores set score=101; raise exception 'invalid marks allowed'; exception when check_violation then null; end;
  -- A Class 9 student is never matched to a Class 10 chapter either.
  begin insert into public.scores(student_id,exam_id,subject_id,topic_id,score)
    values((select id from public.students where class_level=9 limit 1),eid,math_id,math_topic,50);
    raise exception 'reverse cross-class chapter allowed'; exception when check_violation then null; end;
  perform public.test_assert(nine_topic is not null and math_topic is not null, 'class 9 and 10 chapters coexist');
end $$;

-- Atomic import rollback: valid first row must not survive an invalid second row.
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ declare sid bigint; tid bigint; subid bigint; payload jsonb;
begin
  select id into sid from public.students where email='one@test.example';
  select id,subject_id into tid,subid from public.topics where name='Real Numbers' and class_level=10;
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
-- Exam dropdown cleanup: teacher deletes; scores block unless included.
do $$ declare e bigint;
begin
  insert into public.exams(name, exam_date, kind) values ('Deletable exam', current_date + 10, 'Weekly Test') returning id into e;
  perform public.delete_exam(e, false);
  perform public.test_assert(not exists(select 1 from public.exams where id = e), 'scoreless exam deleted by teacher');
  insert into public.exams(name, exam_date, kind) values ('Protected exam', current_date + 11, 'Weekly Test') returning id into e;
  insert into public.scores(student_id, exam_id, subject_id, topic_id, score)
    select student_id, e, subject_id, topic_id, 66 from public.scores
    where exam_id = (select id from public.exams where name='Policy test') limit 1;
  begin
    perform public.delete_exam(e, false);
    raise exception 'exam with scores deleted without include flag';
  exception when others then
    if sqlerrm not like '%p_include_scores%' then raise; end if;
  end;
  perform public.test_assert(exists(select 1 from public.scores where exam_id = e), 'scores survive a blocked delete');
  perform public.delete_exam(e, true);
  perform public.test_assert(not exists(select 1 from public.exams where id = e), 'exam deleted with include flag');
  perform public.test_assert(not exists(select 1 from public.scores where exam_id = e), 'included scores deleted too');
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
-- Regression: the app selects class_level from schedule_details; if any
-- migration recreates upcoming_tests without this view, dashboards fail.
select id, title, test_date, topic, notes, subject, class_level
  from public.schedule_details limit 1;
rollback;
\echo ALL POSTGRESQL RLS TESTS PASSED
