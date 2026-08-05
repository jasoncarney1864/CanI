---
name: "mailrun"
description: "Run Jason Carney's job-search inbox triage across both his personal Gmail (jasonbrookecarney@gmail.com) and his dedicated ops@canido.co inbox (which forwards into that same Gmail account) in a single pass. Trigger whenever the user's message is or contains the word \"mailrun\" (case-insensitive) or the command \"/mailrun\" — e.g. \"mailrun\", \"run mailrun\", \"/mailrun\". This is a separate skill from /sitrep — sitrep reports status, mailrun performs the triage action itself (trashing junk, hard-disqualifying onsite/hybrid leads, drafting replies for review)."
---

# MAILRUN — Combined Inbox Triage (Gmail + ops@canido.co)

Trigger: the user's message contains "mailrun" (any case) or the command "/mailrun", either alone or embedded in a longer message. Do not confuse this with /sitrep — sitrep is a read-only status report; mailrun actively works the inbox.

## Context

Jason Carney (jasonbrookecarney@gmail.com, calls the assistant "Bilbi") runs an active job search out of his personal Gmail. On 2026-08-04 he also set up a dedicated mailbox, **ops@canido.co**, specifically as an assistant-managed inbox ("everything to do with you") — it's configured to **forward all incoming mail into jasonbrookecarney@gmail.com**, so both addresses are reachable through the single existing Gmail connector. No separate mail connector or credential is needed; forwarded mail just shows up in the same Gmail inbox addressed to ops@canido.co.

## What mailrun does, in order

1. **Primary inbox triage (jasonbrookecarney@gmail.com)** — run the established job-search triage rules (below) against inbox threads that haven't been triaged since the last mailrun/manual pass.
2. **ops@canido.co check** — search Gmail for mail addressed to ops@canido.co (e.g. `to:ops@canido.co` or `deliveredto:ops@canido.co`) received since the last check. This inbox is new and not necessarily job-lead traffic — it may contain things Jason has routed directly to the assistant (files, notes, forwarded shares). Summarize what's there plainly rather than auto-applying trash/draft logic, UNLESS a message clearly matches the job-lead pattern (real recruiter, real JD), in which case handle it exactly like the primary inbox.
3. Report one combined summary at the end (see Output below) — don't produce two separate disconnected reports.

## Established triage rules (apply to the primary inbox, and to any ops@canido.co item that is clearly a job lead)

- 100% remote is a hard requirement. Onsite/hybrid roles are hard-disqualified: leave the thread completely untouched — no reply, no trash, no label.
- Direct recruiter/hiring-manager emails with a real job description go through the full flow: evaluate fit, then draft (never send) either a qualifying reply (key details like remote status/comp/end client are missing) or a full pitch reply (the lead is strong and well-specified).
- Spam dressed up as job leads (vague urgency, no named employer/role, "interview ASAP"/"we found jobs near you" bait) gets trashed on sight.
- Blacklisted sender domains get trashed wholesale on sight: robly.com (wildcard — all subdomains), arcamax.com (wildcard), dayinhist.io, financialassistpro.com, loanboostexpress.com, storyfunder.com, leadleaplaunch.com, alerts.myjobhelper.com, send.hellohiring.com, ourjob.net, getacareer.co.uk, pizzazzy.net, yoursmrtadvnces.com, rent2ownship.com, plus job-alert digest senders (alerts@ziprecruiter.com, obs@alerts.jobot.com, amtrak-jobnotification@noreply.jobs2web.com, jobalert@lensa.com). Watch for new domains matching the same vague-urgency-bait pattern; flag and add them to this list going forward.
- Indeed-style/LinkedIn/TheLadders/Wellfound/Obra digest alerts are left untouched (out of scope for this flow — no single reply target/JD).
- **Upwork and Fiverr threads are always left completely untouched** — Jason handles those himself as separate side projects; do not triage, trash, or draft anything in them.
- The assistant drafts replies for Jason to review and send himself — **never send directly**.
- Log every newly-drafted lead into the Smartsheet "Job Search Tracker" (sheet_id 1621144942628740) using the existing column conventions (Company = staffing/recruiting firm that made contact, Client = the named end client when different), and append a summary of the run to the `/areas/job-search.md` memory file.

## Output

At the end of a mailrun pass, report (short lines, no fluff — same tone as sitrep):

- How many threads were reviewed, broken out by primary inbox vs. ops@canido.co
- What was trashed (sender/domain)
- What was hard-disqualified (onsite/hybrid, left untouched) — company/role/location
- What was drafted (company, role, qualifying vs. pitch) — remind Jason these are drafts only, nothing was sent, and he still needs to attach a tailored resume before sending if one wasn't attached
- Anything flagged but not acted on (needs a tailored resume build, a personal callback, a status-only update, etc.)
- Anything unusual or notable found specifically in ops@canido.co, since that inbox's purpose is still being defined day to day

Deliver via SendUserMessage.
