# Which Employee Next: Marketing vs. Human Resources

**Date:** 2026-07-15
**For:** Sam
**From:** Rahul

## The decision

Sales Employee is done. Of the three agents planned for this stretch, two are left: **Marketing** and **Human Resources**. This doc lays out what we found when we compared them, and what we recommend building next.

## How we compared them

We looked at three things for each product:
1. How fast each part is to build
2. How many outside companies (LinkedIn, Indeed, Instagram, TikTok, X/Twitter) we need approval from, and how hard that approval actually is
3. Which pages inside each product depend on each other, so we build them in the right order

## What we found

### Human Resources

HR breaks into 4 parts:
- **Document Library + Onboarding Chat** — HR policy documents + a chat assistant for new hires. Reuses things we've already built for other agents (document storage, the chat/avatar pattern). No outside approval needed.
- **Candidates & Scoring** — resume review, AI scoring, hire recommendations. Runs on our own AI, no outside platform needed.
- **AI Video Interviewer** — an AI-run video interview. Built on the same video-calling technology we already use elsewhere. No outside platform approval needed.
- **Job Postings & Sourcing** — posting jobs to LinkedIn/Indeed, and searching LinkedIn to find candidates.

The first three parts need nothing from any outside company. The fourth part is a real problem — not because it's slow, but because it's currently **not available to us at all**:
- LinkedIn is not accepting new partners for their Job Posting API right now — there is no application to even submit.
- Indeed requires we already have 10+ paying clients before they'll consider a partnership. We don't qualify yet, by their own written rules.
- Searching LinkedIn for candidates has no official access route for a company our size — and scraping LinkedIn instead carries real legal risk. LinkedIn sued and shut down a company last year for doing exactly that (reselling scraped candidate data).

So 3 of HR's 4 parts are fully buildable right now. The 4th is genuinely blocked — not a timing issue, a closed door.

### Marketing

Marketing breaks into 4 parts:
- **AI Content Generator** — turns a text prompt into social media images.
- **Post Composer** — write and preview a post before it goes out.
- **Scheduling Calendar** — plan and queue posts.
- **Analytics** — basic performance reporting.

The generator, composer, and calendar are all straightforward to build. Actually **posting** to Instagram/Facebook, X, TikTok, and LinkedIn does need approval from each platform — but these are normal processes, not closed doors. Typical turnaround is a few weeks per platform, and none of them require us to already have a client base first. It's real work, but it's work we can actually complete.

## The bottom line

Both products need real integration work — that part of your instinct was right. But it's not the same kind of problem:

| | Blocked by |Timeline | Can we get through it? |
|---|---|---|---|
| HR — Job Postings & Sourcing | LinkedIn/Indeed partnership rules | Unknown / possibly never at our size | Not right now |
| Marketing — social posting | Standard platform app review | Weeks per platform | Yes |

Also worth knowing: HR's LinkedIn need (searching for candidates, posting jobs) and Marketing's LinkedIn need (posting content to a company page) are two completely different LinkedIn products. Getting one approved doesn't help with the other at all — there's no shared setup to reuse between them.

## Recommendation

1. **Build HR's other 3 parts first** — Document Library + Onboarding Chat, Candidates & Scoring, AI Video Interviewer. All buildable now, no outside approval needed, and they reuse a lot of what we've already built.
2. **Set aside HR's Job Postings & Sourcing (LinkedIn/Indeed) for now.** Trying to get direct LinkedIn/Indeed partnership ourselves isn't realistic yet. The real options are: (a) go through a company that already has that partnership and route job postings through them, or (b) keep job posting manual for now — we manage listings ourselves, candidates apply through a link we share, no direct LinkedIn/Indeed integration.
3. **Take on Marketing's platform integrations as their own project after that**, in this order: Instagram/Facebook first (fastest, most predictable), X second (fastest to set up), TikTok third (doable but more work to maintain), LinkedIn company-page posting last (slowest of the four, still realistic).

## What we need from you

- Does this order work for the business, or is there a deadline/priority we don't know about that should change it?
- For HR's job posting piece — okay to keep it manual for now, or do you want us to look into a distribution partner?
