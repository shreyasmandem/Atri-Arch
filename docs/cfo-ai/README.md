# Atri Arch business forecast, built with cfo.ai

The hackathon asks for cfo.ai in the build. We used it (app.cfo.ai, "Ari", the AI CFO) for the part of the
project that is not code: whether selling generated house-plan packages is a business, and what drives its cost.

**Prompt given:** Atri Arch sells house-plan packages for Indian homeowners and small builders - INR 1,999 for a
single scheme, INR 7,999 for a full design set with edits - generated in about a minute; 80 paying customers in
month 1, +15 % a month, 8 % of free users converting, about INR 40 of hosting and AI per design.

**What cfo.ai produced** - an editable 12-month model (October 2026 - September 2027) with assumptions,
package mix, monthly P&L, and upside / downside scenarios:

| Base case (12 months) | |
|---|---|
| Paying customers | 2,320 (80 -> ~372 a month) |
| Revenue | INR 81.18 lakh |
| Hosting and AI cost | INR 12.99 lakh |
| Operating profit (before tax, provisional costs) | INR 56.19 lakh |
| Gross margin (AI/hosting only) | 84 % |

Scenarios: downside 5 % growth / 6 % conversion / 15 % full-set mix; upside 20 % / 10 % / 35 %.

**What it caught that we had not priced in** - at 8 % conversion each paying customer has to fund the designs of
12.5 free users, so AI/hosting is about INR 560 per buyer, not INR 40. That is why every design is metered against a per-firm monthly quota and why the studio falls back to its
measured (non-model) reviews whenever a model is slow or rate-limited: the cost per design is the number the
business lives on.

Screenshot: `forecast-assumptions.jpg` (the assumptions table the model is driven by).
