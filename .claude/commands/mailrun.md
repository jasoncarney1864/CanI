---
name: mailrun
description: Triage Jason Carney's job-search email inbox. Trigger whenever the user's message is or contains the word "mailrun" (case-insensitive) or the command "/mailrun" - e.g. "mailrun", "run mailrun", "/mailrun". Scans unread threads in jasonbrookecarney@gmail.com (ops@canido.co auto-forwards into this same inbox, so no separate mailbox needs checking), deletes blacklisted spam, hard-disqualifies onsite/hybrid leads, and drafts (never sends) qualifying or pitch replies for real remote job leads.
---

# Mailrun

A single-inbox triage pass over Jason's job-search email. Companion to `/sitrep` (status catch-up) - this one processes new mail.

## Scope

Search only **jasonbrookecarney@gmail.com**. His dedicated assistant mailbox, ops@canido.co, forwards everything into this same inbox automatically (set up 2026-08-04 via GoDaddy email forwarding, "keep a copy" left on) - there is no separate mailbox to check, and treating them as two searches double-counts mail.

Search query to start: `is:unread -in:draft in:inbox`

## Classification rules, in order

1. **Blacklisted domain spam -> trash immediately, no confirmation needed.**
   Known domains/senders: dayinhist.io, financialassistpro.com, alerts.myjobhelper.com, send.hellohiring.com, leadleaplaunch.com, loanboostexpress.com, storyfunder.com, ourjob.net, pizzazzy.net, getacareer.co.uk, yoursmrtadvnces.com, rent2ownship.com, arcamax.com (wholesale), and the entire *.robly.com network (wholesale - celestialaligned, diyhousehacks, upliftingquotes, timelessopinions, jokeinbox, fundailywords, pollarizing, chaptercrumbs, dailyascensionpost, dayoftheday, sunrisesampler, emsnownews, newstime, bestjobsfinder, and any new subdomain that shows up, since new ones keep appearing).
   Also trash job-alert *agent/digest* senders that aren't real recruiter outreach: alerts@ziprecruiter.com, obs@alerts.jobot.com, amtrak-jobnotification@noreply.jobs2web.com, jobalert@lensa.com.
   New senders matching the same "vague urgency, no named employer/role" shape (funds available, payment pending, interview-asap clickbait) should be trashed too and added to this list going forward.

2. **Out-of-scope mail -> leave untouched, do not act.**
   - Indeed-style job-alert/digest emails with no single reply target or JD.
   - LinkedIn messaging digests and connection-invite emails (no JD to act on - note any that look like a real InMail worth Jason checking directly in LinkedIn, but don't draft from the digest itself).
   - Upwork and Fiverr emails of any kind - separate side projects, explicitly hands-off.
   - CanI project operational noise that now arrives via the ops@canido.co forward: Azure Monitor alerts, GitHub Actions CI failure notifications, Claude status page incidents. Not job-search related - leave alone. If the same alert is firing/resolving repeatedly in a short window, flag it in the summary as a possible flapping alert worth Jason's attention on the ops side, but don't touch the emails.
   - Any personal/financial mail not on the confirmed blacklist (e.g. a bank alert) - flag it in the summary for Jason to eyeball himself rather than auto-trashing, since it isn't a confirmed-fake domain.

3. **Onsite/Hybrid leads -> hard disqualify.** 100% remote is a hard requirement. If a job lead states onsite or hybrid, leave the thread untouched in the inbox (don't trash it, don't reply) and just note it in the summary.

4. **Direct recruiter/hiring-manager leads with a real job description -> full flow.**
   - Strong match + enough detail (remote status, comp/rate, end client all reasonably clear) -> draft a direct pitch reply.
   - Thin JD (missing remote status, comp, or end client) -> draft a qualifying reply asking for the missing pieces before going further.
   - Never send - always leave as a Gmail draft for Jason to review and send himself.
   - If a lead is strong enough to justify a tailored resume, flag it rather than trying to build the resume inline - that goes through the separate fit-check/resume flow.
   - Standard reference-request line when a recruiter pushes for references upfront: "happy to provide references once we've had an initial conversation and I've confirmed this is the right fit."

## Wrap-up

Report a summary: counts trashed / hard-disqualified / drafted, with enough detail on each drafted lead (company, role, contact, remote/comp status, why it's a match or what's missing) that Jason can decide whether to send without re-reading the thread. Call out anything that needs his personal attention rather than a triage action (voicemails, ambiguous financial alerts, possible ops issues, InMail digests worth checking directly).
