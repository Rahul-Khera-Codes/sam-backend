# Lead Researcher — Data Source Verification & Alternatives Research

**Date:** 2026-07-06
**Status:** Proceeding with Apify, per Sam's direction (confirmed 2026-06-24). This doc is a record of what was tested and what else exists, in case Apify becomes a real blocker later.

---

## What we tested — Apify `data-slayer/linkedin-profile-scraper`

Ran 3 live test lookups against real LinkedIn URLs.

**Base scrape (no email lookup):**
- Cost: **~$0.015/profile**
- Time: a few seconds
- Data returned: full work history, education, skills, headline, company info, location — rich and accurate once the correct profile URL was used (two early tests looked "wrong" but turned out to just be the wrong input URL, not an actor bug).

**With "find verified work email" enabled:**
- Cost: **~$0.03/profile** (roughly double)
- Time: **2+ minutes per lookup** — too slow for an interactive "paste a URL, get a card back" experience
- Email confidence comes back as a status like `catch_all` — meaning the domain accepts any email address, which is a weak signal, not a verified individual mailbox match. Some profiles returned no email at all.

**Conclusion:** the actor works and the raw data is solid, but the "verified email" feature is slow and its confidence signal is weaker than the name implies. Nothing here maps to "best time to reach," "pain points/sales angles," or "personal interests" — those still need an LLM step on top of the raw scraped fields, as already assumed in the requirements doc.

We also tried `dev_fusion/linkedin-profile-scraper` (a different Apify actor, ranked as a top 2026 pick in third-party comparisons) — result was worse than data-slayer's actor, so ruled out.

---

## Alternatives researched (not currently in use)

Researched whether a dedicated enrichment platform (not Apify/scraping-based) would do better on email confidence and speed. Findings, for the record:

| Platform | Data completeness | Email confidence | Pricing (self-serve) | API? | Legal posture |
|---|---|---|---|---|---|
| **People Data Labs (PDL)** | Full work history/education/skills, 100+ fields | Claims 85–95% accuracy, no explicit tier system | ~$98/mo for 350 lookups (~$0.28/lookup) | Yes, fast/synchronous | Aggregated/compliance-reviewed sources, **not** systematic LinkedIn scraping — lower legal risk |
| **Apollo.io** | Title, company, employment history | Best tier system: Verified/Guessed/Catch-all | Free/$49/$79 per user, but **real API access needs Organization tier ($350+/mo, 3-seat min)** | Gated behind expensive tier | LinkedIn recently pulled Apollo's own company page over scraping enforcement — active legal risk |
| **Lusha** | Thinner docs on depth | Confidence docs thinner than Apollo's | ~$52/mo cheapest API tier | Yes | Crowdsourced/partnership sourcing — lower risk than direct scraping |
| **RocketReach** | 700M+ profile DB | Markets 98%, real-world tests show ~70–90% | API gated behind $2,099/yr Ultimate plan | Yes, but priciest gate | Aggregation/scraping-adjacent, unclear licensing |
| **Hunter.io** | None — email-only, no profile data | 1 credit/find, 0.5 credit/verify | $49/mo for 2,000 credits | Yes | Not a profile source, pair with something else |
| Proxycurl | — | — | — | — | **Shut down**, ruled out |
| ZoomInfo / Cognism | — | — | Enterprise only, $15K–40K+/yr | Sales-gated | Not viable for a small team |
| Bright Data (LinkedIn dataset API) | — | — | Usage-based | Yes | Still scraping-based — doesn't reduce legal risk |

**If this ever needs revisiting:** the best combo found was **People Data Labs (profile data) + Hunter.io (email verification)** — roughly $0.30–0.35/lead all-in, synchronous (no multi-minute wait), and meaningfully lower legal exposure than any Apify-based scraping approach. Not pursuing this now because Sam explicitly directed **Apify** as the data source (2026-06-24) — this is a real product/vendor decision, not just a technical swap, so it should go back to Sam if we ever want to change it, not be switched silently.

---

## Sources
- [People Data Labs pricing](https://support.peopledatalabs.com/hc/en-us/articles/25794271805211-Pricing-credits)
- [People Data Labs fields](https://docs.peopledatalabs.com/docs/fields)
- [People Data Labs data sources & compliance](https://docs.peopledatalabs.com/docs/data-sources)
- [Apollo.io API pricing](https://docs.apollo.io/docs/api-pricing)
- [Apollo.io Email Status Overview](https://knowledge.apollo.io/hc/en-us/articles/4423314404621-Email-Status-Overview)
- [LinkedIn's crackdown on Apollo.io](https://www.leadgenius.com/resources/linkedins-crackdown-on-data-scrapers-why-apollo-io-and-seamless-ai-were-targeted--and-whos-next)
- [Lusha pricing](https://salesmotion.io/blog/lusha-pricing)
- [RocketReach pricing](https://salesintel.io/blog/rocketreach-pricing-plans/)
- [Hunter.io pricing](https://hunter.io/pricing)
- [ZoomInfo pricing](https://www.cleanlist.ai/blog/2026-03-19-zoominfo-pricing-guide)
- [Cognism pricing](https://salesmotion.io/blog/cognism-pricing)
