-- ============================================================
-- PRISM Phase 1 — Database Schema
-- Run in Supabase SQL Editor. Idempotent where possible (IF NOT EXISTS).
-- ============================================================

-- ===== Waitlist (already exists from earlier — kept as-is) =====
-- create table waitlist (
--   id uuid primary key default gen_random_uuid(),
--   email text unique not null,
--   source text default 'landing_page',
--   invited boolean default false,
--   created_at timestamptz default now()
-- );


-- ===== Users =====
-- Supabase Auth handles the actual auth.users table.
-- This is OUR application-level profile, linked 1:1 to an auth user.
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  tier text not null default 'free' check (tier in ('free', 'pro')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_profiles_email on profiles(email);


-- ===== Assets =====
-- Master list of trackable assets across crypto + stocks.
-- This is reference data, not live prices — live prices stay in cache (Redis), not DB.
create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,                       -- e.g. 'BTC', 'AAPL'
  name text not null,                         -- e.g. 'Bitcoin', 'Apple Inc.'
  asset_class text not null check (asset_class in ('crypto', 'stock')),
  provider_id text,                           -- e.g. coingecko id 'bitcoin', or stock ticker as-is
  is_active boolean default true,
  created_at timestamptz default now(),
  unique(symbol, asset_class)
);

create index if not exists idx_assets_symbol on assets(symbol);
create index if not exists idx_assets_class on assets(asset_class);


-- ===== Watchlist =====
-- User's tracked assets. Free tier capped at 3 — enforced in application logic,
-- but we also guard with a constraint-friendly design (no hard DB limit, since
-- tier rules can change; application layer is the source of truth for limits).
create table if not exists watchlist (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  asset_id uuid not null references assets(id) on delete cascade,
  created_at timestamptz default now(),
  unique(user_id, asset_id)
);

create index if not exists idx_watchlist_user on watchlist(user_id);


-- ===== Signals =====
-- AI-generated signals, cached and refreshed on an interval (not generated per-request).
-- Storing history here also lets us later measure real accuracy — important for trust.
create table if not exists signals (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  direction text not null check (direction in ('bullish', 'bearish', 'neutral')),
  confidence numeric(5,2) not null check (confidence >= 0 and confidence <= 100),
  reasoning text not null,
  model_used text not null,                   -- 'groq' or 'gemini', for auditability
  generated_at timestamptz default now(),
  expires_at timestamptz not null              -- when this signal should be regenerated
);

create index if not exists idx_signals_asset on signals(asset_id);
create index if not exists idx_signals_generated on signals(generated_at desc);

-- Only the latest non-expired signal per asset matters for serving —
-- this view simplifies that lookup.
create or replace view latest_signals as
select distinct on (asset_id) *
from signals
order by asset_id, generated_at desc;


-- ===== Row Level Security =====
-- Enabled for tables users might eventually access directly (future-proofing
-- for when the frontend may talk to Supabase directly for some reads).
-- For now, the backend uses service_role and bypasses these, but they're
-- correct to have in place from day one.

alter table profiles enable row level security;
alter table watchlist enable row level security;

create policy "Users can view own profile" on profiles
  for select using (auth.uid() = id);

create policy "Users can update own profile" on profiles
  for update using (auth.uid() = id);

create policy "Users can view own watchlist" on watchlist
  for select using (auth.uid() = user_id);

create policy "Users can manage own watchlist" on watchlist
  for all using (auth.uid() = user_id);

-- Assets and signals are public read data — no RLS restriction needed,
-- but we still enable RLS and allow public select for consistency/safety.
alter table assets enable row level security;
alter table signals enable row level security;

create policy "Assets are publicly readable" on assets
  for select using (true);

create policy "Signals are publicly readable" on signals
  for select using (true);


-- ===== Seed data: initial tracked assets (Phase 1 scope) =====
insert into assets (symbol, name, asset_class, provider_id) values
  ('BTC', 'Bitcoin', 'crypto', 'bitcoin'),
  ('ETH', 'Ethereum', 'crypto', 'ethereum'),
  ('SOL', 'Solana', 'crypto', 'solana'),
  ('AAPL', 'Apple Inc.', 'stock', 'AAPL'),
  ('TSLA', 'Tesla Inc.', 'stock', 'TSLA'),
  ('MSFT', 'Microsoft Corp.', 'stock', 'MSFT')
on conflict (symbol, asset_class) do nothing;
