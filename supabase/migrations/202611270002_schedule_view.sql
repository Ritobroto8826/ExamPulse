-- ---------------------------------------------------------------------------
-- Fix: schedule_details was never recreated when class_level was added to
-- upcoming_tests. Views keep their original column list (u.* does not pick up
-- later columns), so the app's class-aware schedule fetch failed with a 400
-- ("The operation could not be completed") on the dashboard.
-- ---------------------------------------------------------------------------
drop view public.schedule_details;
create view public.schedule_details with (security_invoker = true) as
select u.*, s.name as subject from public.upcoming_tests u
left join public.subjects s on s.id = u.subject_id;
grant select on public.schedule_details to authenticated;
