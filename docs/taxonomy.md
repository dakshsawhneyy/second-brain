# Taxonomy draft (for user review)

Updated 2026-11-17. Two axes: TOPIC (what it is about) and FORMAT (how it is delivered).
User's rule: AI, self-growth, discipline and professional growth are growth. Gameplays, movies
and similar are entertainment = noise.

## Axis 1: topic

GROWTH
- AI
  - Claude / coding-agent tips
  - Agents and automation
  - LLM engineering (memory, RAG, evals)
  - AI tools and workflows
  - AI news and trends
- Infra and Cloud
  - DevOps / CI/CD
  - SRE and incident response
  - Platform engineering
  - Cloud (AWS, Azure, GCP), Kubernetes, Terraform
  - Cloud security and FinOps
- Startups and Business
  - Startup stories and founder lessons
  - Building and validating products
  - SaaS and pricing
  - Money and wealth building
- Marketing and Distribution
  - Audience and content growth
  - Sales and outreach
  - Positioning and copy
- Self-growth and Discipline
  - Habits and routines
  - Focus and productivity
  - Mindset and psychology
  - Health and energy
- Professional growth
  - Foreign remote jobs, interviewing, negotiation
  - Career strategy, communication, leadership
  - Core engineering (Python, system design)

NOISE
- Entertainment: gameplays, movies, music, comedy, memes, general vlogs
- Uncertain: asked once a week via the bot; the answer trains the scoring

## Axis 2: format
tip or trick | tutorial | podcast or interview | talk or lecture | news or trend | case study or story | opinion | review

## Scoring notes
- Relevance is scored against the two bets: (1) foreign infra startup job, (2) own product.
  Infra, Startups and Business, and Marketing score highest for those bets.
- Entertainment is demoted to tombstones, but time spent on it is still counted in drift stats.
- A video can have one primary topic and up to two secondary topics.
- Multi-topic content (e.g. a podcast across AI, business, marketing): one card, never copied per
  category. The card has a primary topic (the biggest share of the content) plus secondary tags.
  Each key point inside it carries its own topic, using transcript timestamps/chapters when available,
  so retrieval and the "what I learned about X" views find the insight, not the whole episode.
  Time spent is split across topics by segment length, so drift stats are not double-counted.
