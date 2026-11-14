-- Samadhan — seed / reset
-- Re-runnable: truncates everything, then recreates the four demo personas.
-- This IS the reset script. Run it between demo takes.
--
-- All dates are RELATIVE TO current_date, so "closed 8 months ago" and
-- "₹1,000 charged since closure" stay true whichever day we demo.

begin;

truncate table
    proofs, handovers, refund_requests, credit_notes, service_tickets,
    conversation_turns, case_events, call_sessions, cases,
    settlements, invoices, plans, devices, phone_bindings,
    tool_idempotency, merchants
restart identity cascade;

-- Reference sequences restart too, so refs are stable across takes.
alter sequence case_ref_seq     restart with 1041;
alter sequence refund_ref_seq   restart with 2207;
alter sequence pickup_ref_seq   restart with 8841;
alter sequence ticket_ref_seq   restart with 3302;
alter sequence credit_ref_seq   restart with 5521;
alter sequence proof_ref_seq    restart with 9043;
alter sequence handover_ref_seq restart with 1180;

-- =====================================================================
-- M1 — CLOSURE. The real case from slide 2.
-- Shop closed 8 months ago. Soundbox still active. Rent still deducted.
-- =====================================================================
with m as (
    insert into merchants
        (merchant_code, owner_name, shop_name, phone, language_code, city,
         address, shop_status, shop_closed_on, onboarded_on)
    values
        ('M1', 'Lakshmi Devi', 'Lakshmi Provision Store', '+919000000001',
         'te-IN', 'Hyderabad',
         'Shop 14, Moosapet Main Road, Hyderabad 500018',
         -- 8 months + 5 days, so that the charge dated exactly 8 months ago
         -- falls AFTER the closure date. Without the 5 days we get 7
         -- post-closure invoices (₹875) instead of the 8 (₹1,000) the pitch cites.
         'closed', (current_date - interval '8 months' - interval '5 days')::date,
         (current_date - interval '16 months')::date)
    returning id
),
d as (
    insert into devices
        (merchant_id, serial, status, activated_on, last_heartbeat_at)
    select m.id, 'SB-77301', 'active',
           (current_date - interval '16 months')::date,
           -- Last payment taken the day before the shop closed. The closure
           -- tool credits charges after the later of this and the month the
           -- merchant states, so this keeps M1's credit at the pitch's ₹1,000.
           now() - interval '8 months' - interval '6 days'
    from m
    returning id, merchant_id
),
p as (
    insert into plans
        (merchant_id, billed_plan_name, billed_monthly_amount, billing_started_on)
    select m.id, 'Soundbox Rental Standard', 125.00,
           (current_date - interval '16 months')::date
    from m
    returning merchant_id
)
-- 16 monthly charges of ₹125. The last 8 fall AFTER the shop closed,
-- which is the ₹1,000 the merchant is complaining about.
insert into invoices
    (merchant_id, device_id, period_start, period_end, amount, description,
     status, charged_on)
select
    d.merchant_id,
    d.id,
    (current_date - make_interval(months => n))::date,
    (current_date - make_interval(months => n - 1) - interval '1 day')::date,
    125.00,
    'Soundbox monthly rental',
    'paid',
    (current_date - make_interval(months => n))::date
from d, generate_series(16, 1, -1) as n;

insert into settlements (merchant_id, amount_on_hold, status)
select id, 0, 'clear' from merchants where merchant_code = 'M1';

-- =====================================================================
-- M2 — PROMISE MISMATCH. Slide 3: "I was told ₹1 a month, I pay ₹125."
-- 7 months billed at ₹125 against a promised ₹1 → ₹868 overcharged.
-- =====================================================================
with m as (
    insert into merchants
        (merchant_code, owner_name, shop_name, phone, language_code, city,
         address, shop_status, onboarded_on)
    values
        ('M2', 'Imran Qureshi', 'Imran Mobile Repairs', '+919000000002',
         'hi-IN', 'Hyderabad',
         '2-4-18, Charminar Road, Hyderabad 500002',
         'active', (current_date - interval '7 months')::date)
    returning id
),
d as (
    insert into devices
        (merchant_id, serial, status, activated_on, last_heartbeat_at)
    select m.id, 'SB-81144', 'active',
           (current_date - interval '7 months')::date,
           now() - interval '6 minutes'
    from m
    returning id, merchant_id
),
p as (
    insert into plans
        (merchant_id, promised_plan_name, promised_monthly_amount, promised_by,
         promised_on, billed_plan_name, billed_monthly_amount, billing_started_on)
    select m.id,
           'Soundbox Promo ₹1', 1.00,
           'field sales, Hyderabad South',
           (current_date - interval '7 months')::date,
           'Soundbox Rental Standard', 125.00,
           (current_date - interval '7 months')::date
    from m
    returning merchant_id
)
insert into invoices
    (merchant_id, device_id, period_start, period_end, amount, description,
     status, charged_on)
select
    d.merchant_id,
    d.id,
    (current_date - make_interval(months => n))::date,
    (current_date - make_interval(months => n - 1) - interval '1 day')::date,
    125.00,
    'Soundbox monthly rental',
    'paid',
    (current_date - make_interval(months => n))::date
from d, generate_series(7, 1, -1) as n;

insert into settlements (merchant_id, amount_on_hold, status)
select id, 0, 'clear' from merchants where merchant_code = 'M2';

-- =====================================================================
-- M3 — SETTLEMENT HOLD. Slide 3: "My money is on hold."
-- ₹14,200 held on a PAN/GST name mismatch, two documents missing.
-- =====================================================================
with m as (
    insert into merchants
        (merchant_code, owner_name, shop_name, phone, language_code, city,
         address, shop_status, onboarded_on)
    values
        ('M3', 'Anjali Reddy', 'Anjali Fashions', '+919000000003',
         'te-IN', 'Hyderabad',
         'Plot 7, Kukatpally Housing Board, Hyderabad 500072',
         'active', (current_date - interval '14 months')::date)
    returning id
),
d as (
    insert into devices
        (merchant_id, serial, status, activated_on, last_heartbeat_at)
    select m.id, 'SB-64207', 'active',
           (current_date - interval '14 months')::date,
           now() - interval '3 minutes'
    from m
    returning id, merchant_id
),
p as (
    insert into plans
        (merchant_id, billed_plan_name, billed_monthly_amount, billing_started_on)
    select m.id, 'Soundbox Rental Standard', 125.00,
           (current_date - interval '14 months')::date
    from m
    returning merchant_id
)
insert into settlements
    (merchant_id, amount_on_hold, hold_reason_code, hold_reason_plain,
     missing_documents, held_since, expected_release_date, status)
select
    p.merchant_id,
    14200.00,
    'KYC_NAME_MISMATCH',
    'The name on your PAN does not match the name on your GST registration, so the account could not be verified.',
    array['PAN card photo', 'GST certificate'],
    (current_date - interval '16 days')::date,
    (current_date + interval '7 days')::date,
    'on_hold'
from p;

-- =====================================================================
-- M4 — DEVICE FAULT. Slide 3: "The Soundbox stopped speaking."
-- Last heartbeat 11 days ago → troubleshoot, then book a technician.
-- =====================================================================
with m as (
    insert into merchants
        (merchant_code, owner_name, shop_name, phone, language_code, city,
         address, shop_status, onboarded_on)
    values
        ('M4', 'Ravi Kumar', 'Ravi Tea Stall', '+919000000004',
         'te-IN', 'Hyderabad',
         'Beside Bus Depot, Dilsukhnagar, Hyderabad 500060',
         'active', (current_date - interval '9 months')::date)
    returning id
),
d as (
    insert into devices
        (merchant_id, serial, status, activated_on, last_heartbeat_at)
    select m.id, 'SB-50982', 'active',
           (current_date - interval '9 months')::date,
           now() - interval '11 days'
    from m
    returning id, merchant_id
),
p as (
    insert into plans
        (merchant_id, billed_plan_name, billed_monthly_amount, billing_started_on)
    select m.id, 'Soundbox Rental Standard', 125.00,
           (current_date - interval '9 months')::date
    from m
    returning merchant_id
)
insert into invoices
    (merchant_id, device_id, period_start, period_end, amount, description,
     status, charged_on)
select
    d.merchant_id,
    d.id,
    (current_date - make_interval(months => n))::date,
    (current_date - make_interval(months => n - 1) - interval '1 day')::date,
    125.00,
    'Soundbox monthly rental',
    'paid',
    (current_date - make_interval(months => n))::date
from d, generate_series(9, 1, -1) as n;

insert into settlements (merchant_id, amount_on_hold, status)
select id, 0, 'clear' from merchants where merchant_code = 'M4';

commit;

-- ---------------------------------------------------------------- sanity
-- Expected after seeding:
--   M1: 16 invoices, 8 of them after closure = ₹1,000 charged post-closure
--   M2: 7 invoices, ₹868 overcharged vs the promised ₹1/month
--   M3: ₹14,200 on hold, 2 missing documents
--   M4: device silent for 11 days
select
    m.merchant_code,
    m.shop_name,
    m.shop_status,
    m.shop_closed_on,
    count(i.id)                                     as invoices,
    coalesce(sum(i.amount), 0)                      as total_billed,
    coalesce(sum(i.amount) filter (
        where m.shop_closed_on is not null
          and i.charged_on > m.shop_closed_on), 0)  as billed_after_closure,
    p.promised_monthly_amount,
    p.billed_monthly_amount,
    case when p.promised_monthly_amount is not null
         then (p.billed_monthly_amount - p.promised_monthly_amount) * count(i.id)
    end                                             as overcharge,
    s.amount_on_hold,
    (now() - d.last_heartbeat_at)::interval         as device_silent_for
from merchants m
left join invoices    i on i.merchant_id = m.id
left join plans       p on p.merchant_id = m.id
left join settlements s on s.merchant_id = m.id
left join devices     d on d.merchant_id = m.id
group by m.merchant_code, m.shop_name, m.shop_status, m.shop_closed_on,
         p.promised_monthly_amount, p.billed_monthly_amount,
         s.amount_on_hold, d.last_heartbeat_at
order by m.merchant_code;
