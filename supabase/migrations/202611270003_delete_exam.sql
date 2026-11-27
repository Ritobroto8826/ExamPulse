-- ---------------------------------------------------------------------------
-- Score-entry dropdown cleanup: teachers can remove exams. An exam that
-- already carries marks is protected — the delete only proceeds when
-- p_include_scores is explicitly set (the UI forces a confirmation tick).
-- ---------------------------------------------------------------------------
create function public.delete_exam(p_exam_id bigint, p_include_scores boolean default false)
returns void
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.is_teacher() then
    raise insufficient_privilege using message = 'Not authorized';
  end if;
  select count(*) into n from public.scores where exam_id = p_exam_id;
  if n > 0 and not p_include_scores then
    raise exception 'Exam still has % score(s); pass p_include_scores to delete them too.', n;
  end if;
  delete from public.scores where exam_id = p_exam_id;
  delete from public.exams where id = p_exam_id;
end;
$$;
revoke execute on function public.delete_exam(bigint, boolean) from public, anon, authenticated;
grant execute on function public.delete_exam(bigint, boolean) to authenticated;
