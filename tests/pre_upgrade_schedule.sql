-- TEST ONLY: runs between the base migration and the multi-class migration to
-- reproduce a real deployment that already has scheduled chapter tests.
-- The upgrade must backfill upcoming_tests.class_level before its not-null
-- check, or the migration fails on live data (seen on a real project).
\set ON_ERROR_STOP on
insert into public.upcoming_tests(title, test_date, subject_id, topic)
  select 'Pre-upgrade scheduled test', current_date, id, 'Real Numbers'
  from public.subjects where name = 'Mathematics';
