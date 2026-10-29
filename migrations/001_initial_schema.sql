-- Phase 1: minimal durable job table.
-- Run this in Supabase Dashboard > SQL Editor.
create extension if not exists pgcrypto;

create table if not exists public.jobs (
    id uuid primary key default gen_random_uuid(),
    status text not null default 'pending'
        check (status in ('pending', 'processing', 'completed', 'failed')),
    request_type text not null default 'competitor_research',
    request_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists jobs_status_created_at_idx
    on public.jobs (status, created_at);

-- Enable RLS. Phase 1 has no public job endpoints, so no client policies
-- are created yet. The backend uses the Supabase service-role key.
alter table public.jobs enable row level security;
