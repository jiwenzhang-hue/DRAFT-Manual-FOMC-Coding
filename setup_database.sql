-- First create your owner user in Authentication > Users.
-- Replace REPLACE_WITH_OWNER_USER_UUID below with that user's ID.
-- Run once in Supabase SQL Editor. This creates a new dedicated table.

begin;
create table public.fomc_responses (
    id uuid primary key,
    created_at timestamptz not null default now(),
    start_timestamp timestamptz not null,
    end_timestamp timestamptz not null,
    payload jsonb not null,
    constraint valid_timestamps check (end_timestamp >= start_timestamp),
    constraint payload_is_object check (jsonb_typeof(payload) = 'object')
);
alter table public.fomc_responses enable row level security;
revoke all on table public.fomc_responses from public, anon, authenticated;
grant usage on schema public to authenticated, service_role;
grant select on table public.fomc_responses to authenticated;
grant select, insert on table public.fomc_responses to service_role;
create policy owner_reads_responses
on public.fomc_responses for select to authenticated
using ((select auth.uid()) = '6305ea4c-d5e2-4b1e-ad59-3d26511785c6'::uuid);
commit;
