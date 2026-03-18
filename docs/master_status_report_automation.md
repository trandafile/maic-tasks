## Master Status Report – Monthly Automation (Supabase)

Streamlit apps do not run background jobs reliably, so the monthly email should be triggered externally.
Since your preference is **Supabase scheduling / pg_cron**, the recommended approach is:

1) Create a **Supabase Edge Function** (HTTP endpoint) that:
- Generates the Master Status Report markdown
- Sends it via SMTP using the existing settings in the `settings` table
- Emails it to **all approved admins**

2) Schedule the Edge Function to run on the **first day of each month**.

---

## Option A (recommended): Supabase scheduled invocation of Edge Function

### A1. Edge Function sketch (TypeScript)

Create an Edge Function (e.g. `master-status-report`) that:
- Uses the Supabase Service Role key (server-side) to query tables
- Re-implements the report generator logic (Projects → Deliverables → Tasks → Subtasks)
- Queries `users` where `role='admin' and is_approved=true` for recipients
- Uses SMTP settings from the `settings` table to send the email

You can mirror the same sorting rules used in the app:
- deliverables by `deadline` (nulls last)
- tasks by `deadline` (nulls last)
- subtasks by `deadline` (nulls last)

### A2. Scheduling (cron)

If pg_cron is available in your project, schedule it for the 1st day of each month:

- **Cron expression**: `0 7 1 * *` (07:00 UTC on day 1)

Then use a scheduled job to invoke the Edge Function URL.

Exact scheduling commands depend on your Supabase plan/features; the principle is:
- schedule → call HTTPS endpoint

---

## Option B: External runner (fallback)

If scheduled triggers are not available in Supabase:
- run a small Python script via cron/GitHub Actions monthly
- script calls the Edge Function (or directly sends emails using SMTP settings)

---

## Notes

- Ensure SMTP settings are configured in the `settings` table:
  - `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from_name`, `notifications_enabled`
- The app-side “Send via email” uses the same safety checks (notifications_enabled + password presence).

