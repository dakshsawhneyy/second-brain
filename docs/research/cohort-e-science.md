# Cohort E: The science of what changes behaviour and achievement

Date: 2026-11-20. Purpose: design evidence for a strict-but-human accountability mentor bot for a 21-year-old student who hides in comfortable work (building tools) instead of frightening work (applications, outreach).

## How to read this document (verification status)

Web search was partly rate-limited during this session. Every figure is tagged:
- [V] = verified this session against a search result that quoted the figure (URL given).
- [M] = from my background knowledge, NOT re-verified this session. Treat as approximate; check before quoting.
- [?] = I could not confirm and explicitly do not vouch for it.
No citation or number below was invented; where I am unsure I say so. Several of the 10 topics are therefore [M]-heavy (goal-setting, commitment-contract field trials, mentoring, deliberate practice details, wealth books, entrepreneurship). Verify before putting any number in user-facing text. Bot design rules do not depend on exact figures.

Two cross-cutting caveats: (1) most lab effects shrink in field settings and in pre-registered replications; (2) almost no study tests a chatbot enforcing penalties on a young adult, so the harshness conclusions are extrapolations.

---

## 1. Implementation intentions (Gollwitzer) and mental contrasting / WOOP (Oettingen)

Key findings
- Gollwitzer and Sheeran (2006), meta-analysis, 94 independent tests, over 8,000 participants: medium-to-large effect of if-then plans on goal attainment, d = .65 [V]. https://www.socmot.uni-konstanz.de/publications/implementation-intentions-and-goal-achievement-meta-analysis-effects-and-processes
- The effect is on top of a plain goal intention ("I will do X"). Format: "If situation Y arises, then I will do Z."
- Mental contrasting (imagine the wish and the likely obstacle) combined with implementation intentions (MCII/WOOP) improved goal pursuit in many studies; Oettingen's own lab reports medium effects [M]. Independent, large pre-registered replications are fewer [M].

Strength of evidence: Strong for implementation intentions on simple, discrete, cue-bound actions (the d = .65 figure is large-sample but includes publication-bias risk and many small lab studies; later bias-corrected estimates are smaller [M]). Moderate for WOOP (mostly authors' own lab, mixed independent replications [M]).

Boundary conditions / backfires
- Works when the person already has a real goal commitment; does little for goals they do not want [M].
- Needs a specific cue and a concrete response; vague plans do not help.
- Weak for complex, emotionally loaded behaviours where the barrier is fear, not forgetting. Plans fix "I forgot / missed the moment", not "I am terrified" [M, inference].
- Mental contrasting can reduce effort when the person judges success unlikely (it is expectancy-dependent) [M]. For this user, contrasting is useful only if he believes the task is doable; shrink the task first.
- Plans can crowd out flexibility when circumstances change [M].

Design implication
- Every commitment the bot records must be an if-then plan with a time/place cue: "If it is 10:00 and I am at the desk, then I open LinkedIn and send 3 connection requests before opening the editor." Reject "this week I will do outreach".
- Add one obstacle-plan per commitment ("If I feel the urge to open my code project instead, then I send one message first"). Ask the obstacle in his words.
- Do not use contrasting for tasks he thinks are impossible; first reduce to a task he rates 7+/10 likely.

---

## 2. Goal-setting theory (Locke and Latham)

Key findings
- Specific, difficult goals produce higher performance than "do your best" goals; effect sizes in the d ~ 0.5 to 0.8 range in classic reviews [M]. Locke and Latham 2002 "Building a practically useful theory of goal setting" is the main summary [M, not fetched].
- Moderators: goal commitment, feedback on progress, task complexity, self-efficacy [M].
- Learning vs performance goals: on complex, novel tasks, performance (outcome) goals can hurt; learning goals or process goals help [M, Seijts and Latham].
- Goals gone wild (Ordonez, Schweitzer, Galinsky, Bazerman 2009): overly narrow, aggressive goals encourage cheating, risk taking, neglect of unmeasured things, lower intrinsic motivation [M].

Strength: Strong (one of the most replicated findings in organizational psychology), but largely from workplace tasks with measurable output, not fear-laden avoidance.

Boundary conditions / backfires
- Goals without feedback do little.
- Impossible goals plus a harsh consequence invite gaming (reporting "done" for token activity) and shame.
- Outcome goals ("get a job offer") are not controllable; he can fail with perfect effort. Control the input (messages sent, applications submitted).

Design implication
- Set goals on controllable inputs (counts of applications, outreach messages, conversations) with a weekly target slightly above current baseline, not 3x baseline.
- Always pair a goal with feedback within 24 hours (the bot reports the count back).
- Watch for Goodhart gaming: count only evidence he can show (sent folder, screenshot, link), and include a quality sample so he does not spam low-effort messages.

---

## 3. Commitment devices (stickK, SEED, Ariely-Wertenbroch)

Key findings
- SEED (Ashraf, Karlan, Yin 2006, QJE), RCT with 1,777 bank clients in the Philippines [V]: only about 28% of those offered the locked-savings product opened an account [V]; among those offered, savings balances rose by roughly 81% after twelve months [V: sources differ on whether the base is 81% or 82%]. https://povertyactionlab.org/node/1423 and https://ageconsearch.umn.edu/nanna/record/28411/files/dp050917.pdf . Key point: take-up was low, and people with present bias (especially women) took it up more.
- Ariely and Wertenbroch (2002), Psychological Science: students set self-imposed deadlines; they did so (some recognition of self-control problems), and evenly spaced externally imposed deadlines gave the best results; self-set deadlines were better than none but suboptimal [M].
- Health commitment contracts: Halpern et al. (2015, NEJM), smoking cessation, deposit-based contracts yielded higher quit rates than reward-based programmes among those who accepted but acceptance was far lower (roughly 14% vs 90% by my recollection) [M, numbers unverified]. Giné, Karlan, Zinman (2010) CARES smoking deposit: modest increase in quitting at 6 and 12 months among those who signed [M].
- Loss framing: financially framed losses were somewhat more effective than gains in several field trials (Volpp et al. weight loss; Fryer et al. teacher incentives) [M], but loss aversion in the lab is more fragile than popularly claimed (Gal and Rucker 2018 critique) [M].
- Rewards vs punishment and intrinsic motivation: Deci, Koestner, Ryan (1999) meta-analysis found tangible rewards can undermine intrinsic motivation [M]. Gneezy and Rustichini "A fine is a price" (2000): a small fine for late pickups at daycares increased lateness (the fine replaced guilt with a price) [M].
- Gym commitment studies (Royer, Stehr, Sydnor 2015) found commitment contracts raised attendance but heterogeneously and with lapses [M]; I did not verify.

Strength: Moderate. Good field RCTs exist but: low uptake (the people who most need it do not opt in), effects fade after the contract ends, and many studies are small or short [M].

Boundary conditions / backfires
- Self-selection: the people who sign are the sophisticated, willing ones. A user told "your penalty is X" who did not choose it may react with reactance.
- Penalties must be credible, immediate, and proportionate; excessive stakes drive evasion (cheating, quitting the programme).
- Fines can convert a moral/relationship obligation into a transaction (Gneezy and Rustichini).
- Evidence on social accountability vs money is thin; one pre-registered 2026 trial (below, topic 10) points to felt accountability as the mediator, not money.
- The student presumably has little money; Rs-denominated penalties may be trivial or stressful.

Design implication
- Commitment must be chosen by him, in a calm moment, with a written fallback. The bot never imposes a penalty he did not pre-agree.
- Prefer soft, self-chosen costs with a social/identity component (public declaration to a named human, a donation to a cause he dislikes only if he proposes it) over bot-imposed money costs.
- Use evenly spaced short deadlines (daily/weekly) rather than one large far deadline.
- Never escalate the penalty size after a miss; escalate attention instead (see harshness section).

---

## 4. Coaching and mentoring effectiveness

Key findings
- Theeboom, Beersma, van Vianen (2014), meta-analysis of workplace coaching: 18 studies; significant positive effects on all outcomes, from g = 0.43 (coping) up to g = 0.74 (goal-directed self-regulation) [V]. https://research.vu.nl/en/publications/does-coaching-work-a-meta-analysis-on-the-effects-of-coaching-on-/ . Caveat: only 18 studies, mostly small, and within-subject designs inflated effects [V via a citing source].
- Jones, Woods, Guillaume (2016), meta-analysis of workplace coaching: positive effects on learning, behaviour, results; average effect roughly g = 0.4 to 0.7 depending on outcome and rater [M, unverified].
- de Haan and colleagues: coaching effectiveness depends heavily on the coach-client relationship ("working alliance") more than on technique [M]. de Haan, Duckworth, et al. executive coaching studies [M].
- Mentoring: Kram (1985) distinguishes career functions (sponsorship, challenging assignments, exposure) and psychosocial functions (role modelling, acceptance, counselling). Eby et al. (2008) meta-analysis of youth/work mentoring found favourable but small effects (correlations around .1 to .3) with weak effects on objective outcomes versus subjective satisfaction [M]. Mentoring that is formal, short, or low-contact does little [M].
- DuBois et al. (2011) youth mentoring meta-analysis: small average effect (about d = 0.21) [M].

Strength: Moderate for coaching (many self-report outcomes, positive-publication risk, small samples); weak-moderate for objective outcomes. Relationship quality and client motivation are consistent predictors.

Boundary conditions / backfires
- Coaches are chosen by willing clients; effects may not transfer to a mandated process.
- Mentoring with poor chemistry or low frequency can be harmful (Eby's "negative mentoring experiences") [M].
- Coaching improves self-reported self-regulation more reliably than hard outcomes like income.

Design implication
- Effective mentors combine high standards with warmth and acceptance. The bot should state expectations and also acknowledge effort.
- Build the working alliance: remember specifics, refer to his own previous statements, check in at a predictable cadence. A bot that forgets context is a poor alliance.
- Provide career functions explicitly: challenge (next scary task), exposure (who to contact), and reduce friction (draft scripts).
- Track outcomes the user cares about (interviews, replies), not only self-report mood.

---

## 5. Feedback science: Kluger and DeNisi, tough love, SDT, reactance, shame vs guilt

Key findings
- Kluger and DeNisi (1996), Psychological Bulletin: meta-analysis of 607 effect sizes, 23,663 observations; feedback improved performance on average (d = .41) but decreased performance in over one third of cases [V]. https://cris.huji.ac.il/en/publications/the-effects-of-feedback-interventions-on-performance-a-historical/ . Feedback hurt most when it directed attention to the self (praise/criticism of the person) rather than the task, and when it threatened self-esteem [M, the FIT theory].
- Self-Determination Theory (Deci and Ryan): autonomy-supportive styles (offering rationale, choice, acknowledging feelings) predict persistence, well-being, and internalized motivation more than controlling styles (pressure, "should", guilt trips); this is well replicated across health, education and work, though mostly correlational/self-report [M].
- Psychological reactance (Brehm): perceived threats to freedom provoke resistance and boomerang effects; directive messages can produce reactance, especially in young adults [M]. A meta-analysis of reactance in health messages finds controlling language elicits more reactance [M].
- Shame vs guilt (Tangney): guilt (about the act) tends to promote repair and approach; shame (about the self) promotes hiding, avoidance, and defensiveness [M]. The user's core pattern is avoidance, so shame is the very mechanism that would feed it. Caveat: causal evidence for guilt-induced improvement is mixed [M].
- Procrastination and self-blame: see topic 6/7.

Strength: Kluger and DeNisi is strong (large meta-analysis), SDT moderate-strong, shame vs guilt moderate (largely correlational), reactance moderate.

Boundary conditions / backfires
- Feedback about the person ("you are lazy", "you are hiding") is the high-risk class.
- Harshness helps only when: the person has already accepted the standard, the criticism is specific and task-focused, and the relationship is warm enough that it reads as care ("high expectations with assurance of capability", Cohen and Steele's "wise feedback" [M]).
- Controlling pressure can undermine autonomous motivation and lead to compliance then dropout.

Design implication
- Feedback must be about the task and the behaviour, with one concrete next step. Never feedback about character.
- Name the pattern without labelling the person: "Three days, zero outreach messages, 4 commits" rather than "you are hiding".
- Combine strictness on standards with autonomy over means: he picks the how and when; the bot holds the what.
- Use the wise-feedback formula: high standard + belief he can meet it + specific next step.
- No guilt-tripping or shaming language. Escalation = more direct and more frequent, not more emotionally punitive.

---

## 6. Procrastination and avoidance (Steel, Sirois, Pychyl)

Key findings
- Steel (2007) meta-analysis: procrastination relates strongly to low conscientiousness, task aversiveness, low self-efficacy, impulsiveness; temporal motivation theory formalises that value is discounted by delay and increased by expectancy [M; I could not fetch it this session].
- Sirois and Pychyl: procrastination is better seen as short-term mood repair, "giving in to feel good" (emotion regulation failure), than as time management failure [M, consistent with the search summary but unverified].
- Self-forgiveness: Wohl, Pychyl, Bennett (2010): students who forgave themselves for procrastinating on the first midterm procrastinated less on the second; mediated by lower negative affect; observational, a single course, n about 119 to 134 (sources disagree) [V]. https://bps.org.uk/research-digest/cure-procrastination-forgive-yourself
- Interventions that work: reducing task aversiveness (make it smaller/clearer), implementation intentions, temptation bundling and friction control, and emotion-focused strategies (acceptance, self-compassion) [M]. A meta-analysis of procrastination interventions (van Eerde and Klingsieck 2018) found small-to-medium effects, with CBT-type interventions strongest [M].
- Perfectionism and procrastination are only weakly-to-moderately linked overall; the link is mainly via fear of failure/evaluative concerns [V that a Sirois et al. perfectionism meta-analysis exists: https://eprints.whiterose.ac.uk/112533/1/ ; figure not read].
- Exposure-type approaches: graded exposure is the best-supported treatment for avoidance driven by anxiety (social anxiety CBT) [M]. "Rejection therapy" (Jason Comes/Jia Jiang's 100 days of rejection) has no controlled trials that I know of; anecdote only [?]. Rejection-desensitisation logic is plausible (extinction learning) but unproven for job outreach.
- Behavioural activation (depression literature, Cuijpers et al. 2007): scheduling valued activities regardless of mood reliably improves outcomes [M]. Transfers as "act first, motivation follows".

Strength: Moderate for the emotion-regulation account and for CBT-style interventions; weak for rejection therapy specifically; strong for exposure principles in anxiety disorders (a different population).

Boundary conditions / backfires
- Building tools is "productive procrastination": the bot must treat the comfortable work as the avoidance, not as virtue.
- Flooding (huge exposure steps) causes drop-out; exposure must be graded.
- Self-forgiveness helps only when paired with re-engagement, not when it licenses permanent delay.

Design implication
- Reframe misses as an emotion problem: ask "what did you feel right before opening the editor?" (name the feeling, not the excuse).
- Graded exposure ladder for outreach: e.g., level 1 write the message (do not send), 2 send to a low-stakes contact, 3 send to a stranger, 4 ask for a call. Advance when the anxiety rating falls.
- Make the scary task smaller than the comfortable one and put it first in the day ("frightening work before building"); rule: no tool-building before the minimum outreach quota is logged.
- Behavioural-activation rule: act on schedule regardless of mood; log mood after, so he sees that dread predicts poorly.
- Flag "productive procrastination" when commits rise while outreach is zero.

---

## 7. Habit formation, streaks, the what-the-hell effect, self-compassion

Key findings
- Lally et al. (2010): 96 undergraduates followed for 84 days; for the 82 who completed, mean time to plateau of automaticity was about 66 days, ranging 18 to an extrapolated 254 days [V; sources describe 66 as average, not median]. https://www.scientificamerican.com/article/how-long-does-it-really-take-to-form-a-habit/ . Missing a single day did not materially derail habit formation [M from the paper; not re-verified]. The popular "21 days" claim has no scientific basis [M].
- Streaks: motivational effect exists (goal-gradient), but breaking a streak can be demotivating; evidence from apps is correlational/proprietary [M, weak].
- What-the-hell effect (Polivy and Herman, dieting): after a "violation," people abandon self-control entirely. Relapse-prevention work (Marlatt) calls this the abstinence violation effect: attributing a lapse to internal, stable flaws increases full relapse [M].
- Self-compassion after failure: Breines and Chen (2012): self-compassion manipulations increased motivation to improve after a failure; Adams and Leary (2007) found self-compassion reduced the what-the-hell effect among restrained eaters [M, unverified]. Wohl et al. above [V]. Sirois (2015) found a link between self-compassion and health-promoting behaviours in a meta-analysis (reported secondhand, effect sizes not read) [V, via APA Monitor https://www.apa.org/monitor/2016/09/ce-corner].

Strength: Moderate (Lally is small and one sample but well cited; self-compassion evidence is promising but partly correlational and lab-based).

Boundary conditions / backfires
- Habit "automaticity" works for simple cue-response behaviours (drink water) and poorly for effortful, variable, emotionally loaded ones like cold outreach; these stay deliberate [M, inference].
- Self-compassion should not become excuse-making; the studies show it supports re-engagement.
- Streak counters can produce all-or-nothing thinking.

Design implication
- Never celebrate or punish the streak alone. Replace "streak" with "rate over the last 14 days" ("9 of 14 days done").
- Hard rule: after a miss, the first message offers an immediate minimal recovery action ("a one-message day"), never a lecture or a doubled quota. Rule: never double the next day's quota after a miss.
- Treat a lapse as data: "What got in the way?" Then re-plan with an if-then.
- Expect outreach to need conscious effort for months; do not tell him it will become automatic after 21 days.

---

## 8. Deliberate practice (Ericsson / Macnamara) and grit (Duckworth)

Key findings
- Ericsson, Krampe, Tesch-Romer (1993): the violin study; accumulated deliberate practice differentiated expert from good violinists [M].
- Macnamara, Hambrick, Oswald (2014), meta-analysis in Psychological Science: deliberate practice explained 26% of variance in performance in games, 21% music, 18% sports, 4% education, under 1% professions; overall about 12% to 14% (secondary sources say 14%; I could not confirm 12%) [V]. https://pubmed.ncbi.nlm.nih.gov/24986855/ . Ericsson and others argue Macnamara counted loosely defined practice; a reanalysis found cumulative duration explains considerably more variance (a figure of 29% to 61% after attenuation corrections appears in a critique) [V, via search summary].
- Grit: Duckworth et al. (2007) claimed grit predicts success beyond IQ and conscientiousness [M]. Credé, Tynan, Harms (2017) meta-analysis: grit correlates about .84 with conscientiousness (perseverance subscale much more predictive than "consistency of interests") and the overall relationship with performance is modest [M, unverified].

Strength: Deliberate practice: moderate for structured domains (music, chess, sport), weak evidence for professions like job search or entrepreneurship. Grit: weak as a distinct trait, but perseverance on goals is clearly relevant.

Boundary conditions / backfires
- Practice volume helps only if it is targeted, with feedback. More tool-building is volume, not deliberate practice of the skill he needs (selling/outreach).
- Grit rhetoric ("just push through") can encourage ignoring real signals about direction.

Design implication
- Treat outreach and interviewing as skills with measurable reps and feedback: log each attempt, review reply rate and what changed.
- Count "reps of the frightening skill", not hours. Hours of building do not count toward the frightening skill's volume.
- Do not preach "grit"; ask for the next specific rep and a review after 20 reps.

---

## 9. Wealth, entrepreneurship, persistence, effectuation, validation

Key findings
- Stanley and Danko, The Millionaire Next Door (1996): many US millionaires lived below their means, were self-employed, owned ordinary businesses, saved/invested consistently [M]. Methodological weaknesses: surveys of a selected high-net-worth sample, no comparison group of equally frugal people who stayed non-wealthy, survivor bias, US 1990s, and later critiques of the "typical millionaire" framing [M].
- Tom Corley, Rich Habits (2010): self-reported survey of about 177 wealthy and 128 poor (figures from memory) [M]. Self-published/popular, not peer reviewed, uncontrolled, self-report, retrospective, causal claims untenable. Treat as anecdote, not evidence.
- Kahneman and Deaton (2010): emotional well-being plateaus around income of USD 75,000 while life evaluation keeps rising [M]; Killingsworth (2021) and Killingsworth, Kahneman, Mellers (2023) adversarial collaboration reconciled it: for most people well-being rises with income, with a plateau/flatten only for a minority who are unhappy [M]. Only marginally relevant here.
- Effectuation (Sarasvathy 2001): think-aloud study of 27 expert entrepreneurs; they favour means-driven action, affordable loss, partnerships, over prediction [M]. Evidence base is small and qualitative; later quantitative support is mixed [M].
- Customer discovery/validation: Camuffo, Cordova, Gambardella, Spina (2020, Management Science) RCT with Italian startups taught a scientific approach (hypothesis testing); treated firms were more likely to pivot and had higher revenues [M, check before quoting].
- Entrepreneurial persistence: most startups fail; persistence after negative signal is not always rational; survivorship bias in success stories is heavy [M]. Studies of "grit" in founders show modest effects [M].

Strength: Weak for popular wealth habits; moderate for the validation RCT (one trial, a specific context); weak-moderate for effectuation.

Boundary conditions / backfires
- Success narratives are survivorship-biased; "do what millionaires do" is not a causal claim.
- Persistence without feedback or pivoting is sunk-cost behaviour.
- A $1M-by-25 target is extremely low-probability; framing goal failure as personal failure would be harmful.

Design implication
- The bot should not quote wealth-habit claims as scientific. If it cites habits, label them "heuristics, not evidence".
- Emphasise validation behaviour that has some experimental support: talk to potential customers/employers early, run small tests, count conversations. This directly attacks tool-building avoidance.
- Pair persistence with a scheduled review: "after 20 conversations/applications, what did you learn, what do we change?"
- Avoid promising outcomes; hold him to inputs.

---

## 10. AI chatbots as coaches and accountability partners

Key findings
- Schimpf, Voigt, Bohne (arXiv 2603.17887, March 2026), preregistered three-arm RCT, 517 participants, Claude Sonnet-powered AI career coach vs matched questionnaire vs no-support control, two-week follow-up [V]. AI vs control: higher goal progress, d = 0.33, p = .016. AI vs written questionnaire: overall goal progress NOT significantly different. Perceived social accountability was higher with the AI and mediated the AI-vs-questionnaire effect on goal progress (indirect effect 0.15, 95% CI 0.04 to 0.31); self-concordance did not mediate [V]. Preprint, not peer reviewed; the title overstates the direct comparison. https://arxiv.org/abs/2603.17887
- Other AI/chatbot coaching work I remember: Terblanche et al. (2022) RCT of an AI coach for goal attainment found a coaching chatbot improved goal attainment similar to human coaching in a small study [M]; Heinz et al. 2025 (Therabot, NEJM AI) RCT in depression symptoms [M]; these are not about accountability for avoidance. Details unverified.
- Sycophancy: Sharma et al. (Anthropic, 2023) found language models tend to agree with user views and flatter, and preference-trained models can reward it [M]. More recent work on social sycophancy in advice settings [?]. Over-reliance and emotional dependence on chatbots with heavy use: observational/early RCT work (OpenAI-MIT 2025) suggests higher usage correlates with loneliness/dependence [M, unverified].

Strength: Weak-to-moderate and very new. One preregistered RCT, short follow-up, self-reported progress, preprint.

Boundary conditions / backfires
- Two weeks of follow-up says nothing about sustained accountability across months.
- The AI-vs-questionnaire null on direct effect suggests the value is felt accountability, which may fade with novelty.
- Sycophancy is the main risk for a mentor persona: the bot validating excuses, building more tools, praising effort that is avoidance.
- Over-reliance: the user may use the bot as the replacement for the real-world action or real people.

Design implication
- Engineer felt accountability: scheduled check-ins, explicit reference to his earlier commitments, a report of what was done vs promised. Not praise.
- Anti-sycophancy rules: the bot must restate the commitment verbatim and compare it to evidence before responding; it may not accept "I was busy" without asking what was done instead; it should disagree when he rationalises.
- Require evidence (a number, a screenshot) for claims of completion; sample-check.
- Steer toward humans: periodically ask him to name a real person who knows his goal; do not become his only support.
- Include honest uncertainty: the bot should say the evidence is early.

---

## TOP 15 DESIGN RULES (ranked by evidence strength)

1. Use if-then implementation intentions for every commitment (cue, place, action). Evidence: d = .65 across 94 tests [V]. Strongest, most actionable.
2. Set specific, difficult-but-feasible goals on controllable inputs (messages sent, applications), not outcomes. Goal-setting theory is among the best replicated findings [M]; the controllable-input point is inference.
3. Give frequent feedback tied to the goal (within 24 hours; weekly review). Goals without feedback underperform [M].
4. Keep feedback about the task, never the person. Kluger and DeNisi: feedback hurt performance in over a third of cases, mostly self-directed feedback [V for the one-third, M for mechanism].
5. Make the frightening task smaller and put it before the comfortable work (task-aversiveness and mood-repair account of procrastination) [M; Steel, Sirois].
6. Use graded exposure for outreach/rejection anxiety, advancing by ladders [M; strong in anxiety treatment, unproven for job outreach].
7. Reply to lapses with a minimal recovery action, never a punishment or a doubled quota (what-the-hell/abstinence violation effect) [M].
8. Self-compassion framing after a miss plus immediate re-engagement (Wohl et al. 2010 [V] is observational; Breines and Chen [M]).
9. Build a working alliance: continuity, memory of specifics, predictable cadence, warmth plus high standards (coaching meta-analyses g = 0.43 to 0.74 [V]; alliance importance [M]).
10. Autonomy-supportive strictness: he chooses means and deadlines; the bot enforces what he chose (SDT, reactance) [M].
11. Penalties only if self-chosen in advance, small, immediate, and fixed (commitment-device evidence is moderate, uptake low) [V for SEED take-up/savings; M for rest].
12. Evenly spaced short deadlines rather than one distant deadline (Ariely and Wertenbroch) [M].
13. Treat validation talks (customer/employer conversations) and reps of the frightening skill as the unit of progress; review after N reps (Camuffo et al. [M]; deliberate practice [M]).
14. Build real felt accountability, require evidence, and block sycophancy (2026 RCT d = 0.33 vs control; accountability mediation [V], preprint, short follow-up).
15. Do not state wealth-habit claims, 21-day habit claims, or "grit" slogans as science (weak or false evidence) and push him toward real humans in his life, not toward the bot alone [M].

---

## WHAT THE EVIDENCE SAYS ABOUT PENALTIES AND HARSHNESS

What works (moderate evidence)
- Pre-chosen, self-selected commitment contracts with credible stakes: SEED roughly 81% higher savings among those offered, but only 28% opted in [V]. Deposit contracts for smoking beat rewards among acceptors [M].
- High standards delivered with warmth and a clear next step ("wise feedback") [M].
- Direct, specific, task-focused honesty. Kluger and DeNisi show task-focused feedback is the class that helps [V for averages, M for mechanism].
- Social/felt accountability: the 2026 trial identified it as the active ingredient of the AI coach [V].

What backfires or is unsupported
- Shame and character attacks: tied to hiding and avoidance, exactly this user's failure mode [M].
- Controlling language and imposed penalties: reactance, compliance then dropout (SDT, reactance) [M].
- Fines that turn obligation into price (Gneezy and Rustichini) [M].
- Escalating penalty size after repeated failure (what-the-hell effect; relapse after violation) [M].
- Harsh punishment for a person already anxious about exposure and rejection: no evidence it improves approach behaviour; mechanistic reasons to expect more avoidance [M, inference].
- Directly evidence-free: bot-imposed money fines on a student; AI-delivered tough love. I found no trial testing it [?].

Safest escalation design (inference from the above; none of it is directly tested)
1. Level 0 (agreed in advance): daily if-then commitments, evidence of completion logged, neutral report.
2. Level 1, first miss: curious and short. Quote the commitment, ask what happened and what he felt, offer a minimal recovery action today.
3. Level 2, repeated misses (e.g., 3 of 7 days): direct pattern naming without labels ("5 commits, 0 messages this week"), shrink the task to a version he rates 8/10 likely, re-plan the obstacle.
4. Level 3, persistent avoidance (e.g., 2 weeks): firm statement of the standard, remove the escape option (no tool-building until the minimum outreach is logged, a rule he agreed to), invite a human into the loop (a friend or mentor he names).
5. Consequences are only the ones he pre-chose: small, fixed, immediate, never grown after a miss; allow him to renegotiate in a calm weekly review but not mid-avoidance.
6. Safety valves: if he shows signs of distress, hopelessness, or sustained withdrawal, drop to supportive mode and suggest talking to a person or professional. The bot is not a therapist.
7. Return to warmth: every harsh message is followed by a concrete route back and, when earned, specific acknowledgement of the exact behaviour done.

Strict about standards and evidence; gentle about identity; and escalate attention and structure, never humiliation or penalty size.

---

## Key source URLs
- Implementation intentions meta-analysis: https://www.socmot.uni-konstanz.de/publications/implementation-intentions-and-goal-achievement-meta-analysis-effects-and-processes
- Kluger and DeNisi: https://cris.huji.ac.il/en/publications/the-effects-of-feedback-interventions-on-performance-a-historical/
- Lally habit: https://www.scientificamerican.com/article/how-long-does-it-really-take-to-form-a-habit/
- Macnamara deliberate practice: https://pubmed.ncbi.nlm.nih.gov/24986855/
- Theeboom coaching meta-analysis: https://research.vu.nl/en/publications/does-coaching-work-a-meta-analysis-on-the-effects-of-coaching-on-/
- SEED: https://povertyactionlab.org/node/1423 ; https://ageconsearch.umn.edu/nanna/record/28411/files/dp050917.pdf
- Self-forgiveness and procrastination: https://bps.org.uk/research-digest/cure-procrastination-forgive-yourself
- AI goal-setting RCT (preprint): https://arxiv.org/abs/2603.17887
- Sirois perfectionism/procrastination meta-analysis: https://eprints.whiterose.ac.uk/112533/1/Sirois%20et%20al%20in%20press%20EJP%20Procrastination%20%26%20Perfectionism%20meta-analysis.pdf
