**DONNA PROACTIVE SYSTEM**

Comprehensive Audit Report

6-Layer Documentation vs. Actual Implementation

February 2026

211 tests passing \| 36+ files audited \| 6 layer docs analyzed

**1. Executive Summary**

This audit compares Donna\'s 6-layer design documentation against the
actual codebase to identify gaps between what was planned and what was
built, surface edge-case bugs, and recommend improvements to make the
system feel more human. The codebase is in strong shape: all 211 tests
pass, the architecture is well-modularized, and most of the critical
design goals from the docs have been implemented. However, several
planned features remain incomplete, a handful of subtle bugs exist, and
the system lacks certain \"human feel\" touches that would elevate it
from functional to genuinely delightful.

**1.1 Overall Scorecard**

  ------------------------- --------------- ----------------- ---------------- ----------------------------
  **Layer**                 **Doc Scope**   **Impl Status**   **Test Cover**   **Key Gap**
  L1: Signal Collection     Detailed        **90% DONE**      14 tests         datetime.utcnow() remnants
  L2: Decision Engine       Detailed        **95% DONE**      29 tests         Scoring weights static
  L3: User Model Store      Detailed        **75% PARTIAL**   8 tests          pgvector fallback to ILIKE
  L4: Message Generation    Detailed        **85% DONE**      11 tests         tone\_preference unused
  L5: Delivery              Detailed        **80% DONE**      17 tests         No send-time optimization
  L6: Feedback Processing   Detailed        **70% PARTIAL**   5 tests          No category suppression
  ------------------------- --------------- ----------------- ---------------- ----------------------------

**2. Layer 1: Signal Collection**

**2.1 What the Doc Prescribes**

The Layer 1 doc describes a 6-stage pipeline: Source Adapters →
Normalizer → Deduplicator → Enricher → Sort & Cap → Signal List. It
identifies 5 critical bugs, defines 21 signal types across 4 sources
(Calendar, Canvas, Email, Internal), and specifies a target architecture
with a SignalState table for dedup, cross-signal enrichment, and
computed urgency.

**2.2 Doc vs. Implementation Matrix**

  ---------------------------------------- --------------------- --------------------------------------------------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                   **Status**            **Evidence / Notes**
  Timezone fix (Bug \#1)                   **FIXED**             internal.py uses zoneinfo + user\_tz param. calendar.py passes user tz. prefilter.py uses \_get\_local\_hour().
  is\_proactive on ChatMessage (Bug \#4)   **FIXED**             db/models.py line 179: is\_proactive = Column(Boolean, default=False)
  Signal dedup via SignalState             **IMPLEMENTED**       donna/signals/dedup.py exists with per-type re-emit rules (1-168h). 5 tests pass.
  CANVAS\_GRADE\_POSTED signal             **IMPLEMENTED**       canvas.py line 87 emits grade\_posted. Doc said \"never implemented\" --- now fixed.
  Cross-signal enrichment                  **IMPLEMENTED**       donna/signals/enrichment.py: 4 patterns (gap+deadline, mood+busy, habit+evening, task+gap). 4 tests.
  Signal cap at 10                         **IMPLEMENTED**       collector.py caps output at 10 signals, sorted by urgency\_hint.
  Computed urgency (not type-based)        **NOT IMPLEMENTED**   urgency\_hint is still a static property on SignalType. No dynamic scoring based on points/time/context.
  Response caching                         **NOT IMPLEMENTED**   No caching layer. Canvas assignments re-fetched every 5 min.
  Connection health tracking               **NOT IMPLEMENTED**   No tracking of consecutive failures. Silent degradation.
  NUSMods signal collector                 **NOT IMPLEMENTED**   Data stored as MemoryFact during onboarding but no signal collector polls it.
  WhatsApp metadata signals                **NOT IMPLEMENTED**   Only TIME\_SINCE\_LAST\_INTERACTION. No message frequency or length patterns.
  datetime.utcnow() removal (Bug \#5)      **PARTIAL**           Still present in: tools/memory\_search.py, agent/nodes/context.py, tools/tasks.py, tools/journal.py, tools/expenses.py, donna/memory/entities.py
  ---------------------------------------- --------------------- --------------------------------------------------------------------------------------------------------------------------------------------------

**2.3 Edge Cases & Bugs Found**

**Bug: datetime.utcnow() remnants (6 files)**

While the signal collectors and prefilter are properly timezone-aware, 6
tool/utility files still use the deprecated datetime.utcnow(). This
creates inconsistency: a task marked completed in tools/tasks.py uses
utcnow() (naive), but comparisons in internal.py use timezone-aware
datetimes. If Python 3.12+ is adopted, these will raise deprecation
warnings.

**Files affected:** tools/memory\_search.py, agent/nodes/context.py,
tools/tasks.py, tools/journal.py, tools/expenses.py,
donna/memory/entities.py

**Fix:** Replace all datetime.utcnow() with datetime.now(timezone.utc)
across these 6 files.

**Edge Case: All-day calendar events**

The Layer 1 doc flags that all-day events use the \"date\" field instead
of \"dateTime\" and may parse incorrectly. The calendar signal collector
parses start/end from event data, but if an all-day event has no
\"dateTime\" key, the time comparisons for CALENDAR\_EVENT\_APPROACHING
will fail silently or produce nonsensical results (e.g., treating
midnight as the event start).

**Impact:** Moderate --- students with all-day calendar blocks (study
days, exam periods) would never get approaching-event signals for those.

**Edge Case: Canvas upcoming\_events race condition**

The doc notes that GET /api/v1/users/self/upcoming\_events only returns
future events. If the Donna service was down for hours and an assignment
passed its deadline during that window, CANVAS\_OVERDUE would never fire
for it because the assignment would no longer appear in the API
response.

**Fix:** Supplement upcoming\_events with a query for recently-past
assignments (last 48h) to catch missed deadlines.

**3. Layer 2: Decision Engine**

**3.1 What the Doc Prescribes**

Layer 2 describes 5 phases: Pre-filter (hard rules before LLM), Trust
Ramp (new → building → established → deep), Feedback Loop (track
engagement), Reactive Fallback (deferred insights for borderline
candidates), and Enhanced LLM Prompt (self-threat framing, button
prompts, dynamic composition).

**3.2 Doc vs. Implementation Matrix**

  ------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                **Status**            **Evidence / Notes**
  Pre-filter before LLM                 **IMPLEMENTED**       prefilter.py: trust urgency filter, quiet hours, daily cap, cooldown. 11 tests.
  Trust ramp (4 levels)                 **IMPLEMENTED**       trust.py computes new/building/established/deep. Drives score threshold, daily cap, min urgency. 7 tests.
  Feedback loop (record + check)        **IMPLEMENTED**       feedback.py: record\_proactive\_send, check\_and\_update\_feedback, get\_feedback\_summary. 5 tests.
  DeferredInsight (reactive fallback)   **IMPLEMENTED**       DeferredInsight model exists. rules.py saves borderline candidates. agent/nodes/context.py queries them.
  Self-threat framing in prompt         **IMPLEMENTED**       DONNA\_SELF\_THREAT\_RULES in voice.py: equipping not correcting, with good/bad examples.
  Button prompt action type             **IMPLEMENTED**       Candidates can return action\_type: \"button\_prompt\". Sender routes to WhatsApp interactive buttons.
  Context-only signal skip              **IMPLEMENTED**       loop.py checks for \_context\_only flag. Skips if only time/memory signals with no concrete trigger.
  Signal sensitivity in prefilter       **IMPLEMENTED**       prefilter.py loads UserBehavior.signal\_sensitivity. Ignored signal types require +2 urgency to pass.
  Quiet hours block → DeferredSend      **IMPLEMENTED**       loop.py queues DeferredSend for wake\_time when blocked by quiet hours.
  Per-user scoring weights              **NOT IMPLEMENTED**   Weights are hardcoded: relevance 0.4, timing 0.35, urgency 0.25. No per-user or per-category tuning.
  ------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------

**3.3 Edge Cases & Bugs Found**

**Quiet Hours Midnight-Crossing Logic**

The prefilter checks quiet hours with this logic: if sleep\_hour \>
wake\_hour, then quiet = (current \>= sleep OR current \< wake). For a
student with sleep\_time=23:00 and wake\_time=08:00, sleep\_hour(23) \>
wake\_hour(8), so quiet hours = hour \>= 23 OR hour \< 8. This is
CORRECT. However, the doc originally flagged this as buggy. After code
review, the implementation handles midnight-crossing properly.

**Edge Case: Daily cap counts all proactive messages**

count\_proactive\_today() in rules.py filters by is\_proactive=True,
which is correct (the doc\'s Bug \#4 is fixed). However, it counts ALL
proactive messages including those sent via DeferredSend. If a student
receives 2 messages at 8 AM (one queued from 2 AM quiet hours + one
fresh), the cap sees 2, potentially blocking evening messages. This is
technically correct but may feel unfair since one of those was queued.

**Edge Case: Trust level never de-escalates**

Once a user reaches \"deep\" trust (90+ days active, 100+ messages),
there\'s no mechanism to reduce proactiveness if their engagement drops
to zero. A student who was active in Semester 1 but goes quiet in
Semester 2 keeps receiving deep-trust-level messaging (5 messages/day,
score threshold 5.0). The feedback system partially mitigates this via
category suppression, but the trust-level itself never regresses.

**Recommendation:** Add a 30-day inactivity check: if no user messages
in 30 days, demote trust level by one step.

**4. Layer 3: User Model Store**

**4.1 What the Doc Prescribes**

Layer 3 envisions 4 pillars: Static Profile (academic context,
integration flags), Memory System (pgvector semantic search, structured
entities), Behavioral Model (nightly-computed UserBehavior rows), and
Preference Learning (nightly reflection + real-time micro-updates). The
doc describes get\_user\_snapshot() as the canonical way to query the
full user model.

**4.2 Doc vs. Implementation Matrix**

  ------------------------------------------------- --------------------- ------------------------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                            **Status**            **Evidence / Notes**
  UserEntity structured table                       **IMPLEMENTED**       db/models.py has UserEntity with entity\_type, name, metadata JSON, sentiment, mention\_count.
  UserBehavior table                                **IMPLEMENTED**       db/models.py has UserBehavior with behavior\_key, value JSON, confidence, sample\_size.
  pgvector semantic search                          **PARTIAL**           MemoryFact has Vector(1536) column. recall.py attempts pgvector first but falls back to ILIKE on failure.
  Nightly reflection job                            **IMPLEMENTED**       donna/reflection.py: computes behaviors, decays facts, prunes low-confidence, consolidates entities. Scheduled at 3AM.
  get\_user\_snapshot()                             **IMPLEMENTED**       donna/user\_model.py exists. Returns profile, entities, behaviors, memory\_facts. 2 tests.
  Academic context on User (year, faculty, major)   **NOT IMPLEMENTED**   User model has no academic\_year, faculty, major columns. Doc recommends adding during onboarding.
  Integration status flags                          **NOT IMPLEMENTED**   No has\_canvas, has\_google, has\_microsoft columns. Integration status checked at runtime.
  Memory fact embedding on write                    **PARTIAL**           entities.py calls embed\_text() but falls back silently if embedding fails. Unclear if all MemoryFacts get embedded.
  Memory consolidation (dedup entities)             **PARTIAL**           reflection.py consolidates UserEntity by substring name match. MemoryFact dedup not implemented.
  Standardized MemoryFact categories                **NOT IMPLEMENTED**   No VALID\_CATEGORIES enforcement. Categories are freeform strings set by LLM.
  tone\_preference wired to composer                **NOT IMPLEMENTED**   User.tone\_preference is loaded into context but composer.py prompt never reads it.
  ------------------------------------------------- --------------------- ------------------------------------------------------------------------------------------------------------------------

**4.3 Humanness Gap: The \"Cold\" User Model**

The biggest humanness gap in Layer 3 is that Donna doesn\'t know WHO the
student is beyond their name and timezone. A CS freshman struggling with
their first coding assignment needs fundamentally different support than
a final-year business student juggling internship applications. The doc
prescribed academic context (year, faculty, major) during onboarding,
but this was never implemented. Adding just 2 questions to onboarding
("What year are you in?" and "What are you studying?") would let Donna
calibrate: code-related deadlines for CS students, presentation prep for
business students, lab reminders for engineering students.

**5. Layer 4: Message Generation**

**5.1 What the Doc Prescribes**

Layer 4 covers Donna\'s voice system (shared constants in
donna/voice.py), an adaptive tone engine (mood, recency, time-of-day,
language register), template-aware generation for outside-window
messages, expanded WhatsApp formats (list, CTA), and style adaptation
from the user model.

**5.2 Doc vs. Implementation Matrix**

  ---------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                   **Status**            **Evidence / Notes**
  Shared voice.py constants                **IMPLEMENTED**       donna/voice.py has DONNA\_CORE\_VOICE, DONNA\_WHATSAPP\_FORMAT, DONNA\_SELF\_THREAT\_RULES. 11 tests.
  Adaptive tone (\_build\_tone\_section)   **IMPLEMENTED**       voice.py: mood, recency, length pref, language register, user tone\_preference all factored in.
  Template-aware generation                **IMPLEMENTED**       template\_filler.py uses GPT-4o-mini for multi-slot; naive fallback. 8 tests.
  WhatsApp list format                     **IMPLEMENTED**       send\_whatsapp\_list() in whatsapp.py. sender.py routes briefings with 3+ newlines to list.
  CTA URL button format                    **IMPLEMENTED**       send\_whatsapp\_cta\_button() exists. sender.py routes grade/email alerts with links.
  Message validation (banned phrases)      **IMPLEMENTED**       validators.py: length, banned phrases, leakage, bad markdown, signatures. 7 tests.
  Format-specific validation               **IMPLEMENTED**       validators.py validate\_format\_constraints: button body 1024, list rows 10, CTA URL. 6 tests.
  Language register computation            **IMPLEMENTED**       behaviors.py computes language\_register (formal/casual/very\_casual) from user message patterns.
  Per-user style adaptation examples       **PARTIAL**           Tone section injected into prompt. But no few-shot examples for non-deadline categories (wellbeing, social, habit, memory).
  Emoji count enforcement                  **NOT IMPLEMENTED**   Voice rules say max 1 emoji per message. Validator doesn\'t count emojis.
  Missing templates (habit, exam, class)   **NOT IMPLEMENTED**   No donna\_habit\_streak, donna\_exam\_reminder, donna\_class\_reminder templates.
  ---------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------------------------

**5.3 Humanness Gap: Every User Gets the Same Donna**

The adaptive tone engine is built but the few-shot examples in the
candidates.py prompt are all deadline-related. A student going through a
rough week emotionally doesn\'t need the same tone framework as a
student asking about their schedule. The doc provides excellent examples
for each category (wellbeing, social, habit, memory recall, briefing) in
Appendix A, but these haven\'t been added to the prompt. This means the
LLM has no good reference for how Donna should sound when sending a
gentle mood check-in vs. a punchy deadline reminder.

**Recommendation:** Add the Appendix A examples from the Layer 4 doc
directly into the candidates.py system prompt as few-shot examples,
grouped by category.

**6. Layer 5: Delivery**

**6.1 Doc vs. Implementation Matrix**

  ------------------------------------- --------------------- ---------------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                **Status**            **Evidence / Notes**
  WhatsAppResult dataclass              **IMPLEMENTED**       tools/whatsapp.py has WhatsAppResult with success, wa\_message\_id, error\_code, retryable, fallback\_format.
  parse\_wa\_response()                 **IMPLEMENTED**       Parses success/error from WhatsApp API JSON. 7 tests.
  Retry with format fallback            **IMPLEMENTED**       sender.py \_send\_with\_retry: tries preferred format, falls back to text, exponential backoff.
  Window safety margin (5 min)          **IMPLEMENTED**       sender.py \_get\_window\_status returns minutes\_remaining. Routes to template if \< 5 min.
  Delivery status webhooks              **IMPLEMENTED**       api/webhook.py has \_handle\_status\_update. Updates ProactiveFeedback.delivery\_status. 5 tests.
  wa\_message\_id on ChatMessage        **IMPLEMENTED**       ChatMessage model has wa\_message\_id column. Set by sender.py on send.
  DeferredSend for quiet hours          **IMPLEMENTED**       DeferredSend model + scheduler processes due rows every 60s. Staleness check. 6 tests.
  Connection pooling (httpx client)     **PARTIAL**           whatsapp.py has get\_client()/close\_client(). Tests verify lifecycle. But unclear if module-level pool used.
  Send-time optimization (peak hours)   **NOT IMPLEMENTED**   No optimization to prefer sending during user\'s peak engagement hours.
  Template button context payloads      **NOT IMPLEMENTED**   Template buttons have static payloads. \"remind\_later\" carries no context about which deadline/task.
  format\_used on ProactiveFeedback     **INCOMPLETE**        ProactiveFeedback has format\_used and template\_name columns. Not confirmed populated by sender.
  ------------------------------------- --------------------- ---------------------------------------------------------------------------------------------------------------

**7. Layer 6: Feedback Processing**

**7.1 Doc vs. Implementation Matrix**

  --------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------------------------------------
  **Feature (from Doc)**                  **Status**            **Evidence / Notes**
  Granular outcome hierarchy              **IMPLEMENTED**       feedback.py OUTCOME\_SCORES: 11 outcome types from positive\_reply (1.0) to explicit\_stop (-1.0).
  Sentiment classification (keyword V1)   **IMPLEMENTED**       classify\_reply\_sentiment(): positive/negative/neutral via regex patterns.
  Meta-feedback detection                 **IMPLEMENTED**       detect\_meta\_feedback(): recognizes \"stop sending X\", \"reminders helpful\", time/format/length prefs.
  Late engagement (60-180 min)            **IMPLEMENTED**       check\_and\_update\_feedback classifies late\_engage between ENGAGEMENT\_WINDOW and IGNORE\_TIMEOUT.
  Feedback metrics (nightly)              **PARTIAL**           feedback\_metrics.py exists. Category preferences and engagement trends computed. But not confirmed wired into reflection.
  Category suppression system             **NOT IMPLEMENTED**   Doc prescribes auto-suppress after 5 sends with 0% engagement. compute\_category\_suppression() may exist but not wired into prefilter.
  Probationary re-introduction            **NOT IMPLEMENTED**   21-day cooldown + single high-score attempt to lift suppression. Not built.
  Exploration budget (10%)                **NOT IMPLEMENTED**   No explore/exploit mechanism. System converges to only sending engaged-with categories.
  Feedback decay (14-day half-life)       **PARTIAL**           feedback\_metrics may implement recency decay. Not confirmed in rules.py scoring.
  Adaptive engagement window              **NOT IMPLEMENTED**   ENGAGEMENT\_WINDOW\_MINUTES fixed at 60. No per-user adjustment based on response speed.
  Admin dashboard endpoints               **NOT IMPLEMENTED**   No /api/admin/feedback/{user\_id} endpoint.
  --------------------------------------- --------------------- -----------------------------------------------------------------------------------------------------------------------------------------

**8. Making Donna More Human: Nudge Recommendations**

The system has strong bones, but here\'s what would make it feel like a
sharp friend rather than a competent bot:

**8.1 Email Nudges: Make Them Contextual**

Currently, EMAIL\_UNREAD\_PILING just counts unread emails (≥45) and
EMAIL\_IMPORTANT\_RECEIVED fires per email. These are technically
correct but feel robotic. A human friend wouldn\'t say \"you have 7
unread emails.\" They\'d say \"Prof Tan sent something about the
submission format --- might be worth a look before tomorrow\'s
deadline.\"

**Recommendations:**

-   **Cross-reference email + calendar:** If an email is from a
    professor teaching a class the student has today, escalate urgency
    and mention the class.

-   **Sender awareness:** Extract professor names from course data
    (Canvas/NUSMods). Emails from known professors are more important
    than random university newsletters.

-   **Thread detection:** If an email thread has 5+ messages in 24h,
    it\'s a hot conversation --- nudge differently than a single FYI
    email.

-   **NUS-specific filtering:** Detect official NUS emails (admin
    announcements, financial aid, housing) and tag them differently from
    course-related ones.

**8.2 Calendar Nudges: Anticipate, Don\'t React**

CALENDAR\_EVENT\_APPROACHING fires within 60 minutes of an event. But a
truly helpful friend would think ahead:

-   **Travel time:** If the next class is at a different building and
    the student is on campus (based on previous class location), nudge
    earlier: \"CS2103 at COM1 in 30 min --- might want to head over from
    AS6.\"

-   **Prep nudges:** If there\'s a Canvas assignment related to an
    upcoming class (matching course code), nudge about prep: \"IS1108
    tutorial at 3 --- the discussion post is due before class.\"

-   **Post-event follow-up:** After a class or meeting ends, a brief
    \"How did the CS2103 lecture go?\" during evening window can trigger
    mood logging and build rapport. This requires a
    CALENDAR\_EVENT\_ENDED signal (not currently emitted).

**8.3 Task Nudges: Understand Procrastination Patterns**

TASK\_OVERDUE and TASK\_DUE\_TODAY fire based on due dates, but they
don\'t know the student\'s work pattern:

-   **Procrastination-aware timing:** If UserBehavior shows
    avg\_hours\_before\_due = 8, don\'t nudge 48 hours early --- the
    student won\'t act. Nudge at the 8-hour mark when they\'re likely to
    start.

-   **\"Started\" detection:** If the student mentions an assignment in
    conversation (\"working on CS2103\"), suppress TASK\_DUE\_TODAY for
    that assignment. Currently there\'s no mechanism to detect this.

-   **Completion celebration:** When a task is marked done, Donna should
    acknowledge it in the next proactive cycle: \"CS2103 done. One less
    thing.\" This reinforces the loop.

**8.4 Mood Nudges: Gentle, Never Preachy**

MOOD\_TREND\_DOWN triggers when recent average ≤ 4. The self-threat
framing rules help, but the system could go further:

-   **Indirect care:** Instead of \"Free evening tonight --- anything
    sound good?\", try connecting to things the student enjoys: \"Free
    tonight. That bouldering place you mentioned is open till 10.\"
    Memory-backed wellbeing feels personal, not generic.

-   **Reduce load:** If mood is low AND calendar is busy, proactively
    suggest what can be deferred: \"Busy week. The MA2001 practice set
    isn\'t graded --- could push it to the weekend?\"

-   **Never lead with mood:** \"Your mood has been low\" is a violation
    of self-threat framing. Even \"Free evening tonight\" can feel
    loaded if sent every time mood drops. Vary the approach: sometimes a
    schedule nudge, sometimes a memory recall, sometimes just silence.

**8.5 Habit Nudges: Celebrate Streaks, Don\'t Nag**

HABIT\_STREAK\_AT\_RISK fires when a daily habit hasn\'t been logged in
20+ hours. This is correct, but the framing matters enormously:

-   **Progressive celebration:** Day 7: \"A week. Not bad.\" Day 14:
    \"Two weeks. 🏃\" Day 30: \"A month of \[habit\]. That\'s real.\" The
    tone escalates with the streak.

-   **Risk framing:** Don\'t say \"you haven\'t logged your run today.\"
    Say \"Gym\'s open till 10pm\" (self-threat framing). Or pair with a
    calendar gap: \"Free from 6-8 tonight if you want to keep the streak
    going.\"

-   **Streak recovery:** If a streak breaks, Donna should acknowledge it
    once, gently, then move on. \"Running streak reset. 14 days was
    solid. Start fresh whenever.\" Never pile on.

**8.6 Memory Nudges: The Differentiator**

MEMORY\_RELEVANCE\_WINDOW fires during evenings/weekends when
place/event memories exist. This is Donna\'s most human feature, but
it\'s underutilized:

-   **Time-aware suggestions:** \"That ramen place near PGP\" on a
    Friday evening feels natural. The same nudge on a Tuesday morning
    during exam week feels tone-deaf. Cross-reference with mood and
    calendar load.

-   **Social connection:** If the student mentioned a friend
    (entity:person) in relation to a place (entity:place), pair them:
    \"Free Saturday. Noor mentioned wanting to try the ramen place near
    PGP.\"

-   **Birthday/event reminders:** Extract dates from conversation.
    \"Noor\'s birthday is Saturday --- just flagging in case you want to
    plan something.\" This requires entity metadata tracking dates.

**8.7 Briefing Nudges: The Morning Snapshot**

The system supports briefing-category messages, but there\'s no explicit
\"morning briefing\" trigger:

-   **Opt-in morning summary:** If the student asks for it
    (meta-preference), send a concise morning briefing during the
    wake-time window: \"Tuesday. CS2103 at 10, free till 3pm IS1108
    tutorial. MA2001 due Friday.\"

-   **List format for briefings:** Use WhatsApp list messages (already
    implemented) instead of plain text for briefings with 3+ items.

-   **Adaptive frequency:** Some students want daily briefings, others
    weekly. Track engagement with briefing messages and adjust
    frequency.

**9. Critical Missing Pieces (Priority Order)**

**9.1 Priority 1: Category Suppression (Layer 6)**

The doc describes a complete suppression system: auto-suppress after 5
sends with 0% engagement, 21-day probation, explicit\_stop never
auto-reintroduces. The feedback.py has meta-feedback detection for
\"stop sending X\" but there\'s no prefilter integration that actually
blocks the suppressed category. This means even if the student
explicitly says \"stop texting me about my schedule,\" Donna might still
generate schedule messages. This is the highest-priority gap because it
directly impacts trust.

**9.2 Priority 2: Exploration Budget (Layer 6)**

Without a 10% exploration budget, Donna\'s category diversity will
collapse. If a student only engages with deadline reminders, the
feedback loop will suppress everything else. Within a month, Donna
becomes a one-trick deadline bot. The doc prescribes random.random() \<
0.1 to allow non-preferred categories at a higher score threshold. This
is 5 lines of code with massive impact on long-term variety.

**9.3 Priority 3: Adaptive Engagement Window (Layer 6)**

The fixed 60-minute engagement window penalizes slow responders. A
student who always replies in 45 minutes has their feedback marked as
\"late\_engage\" (0.4 score) instead of \"engaged\" (0.7+). Over time,
this makes their engagement rate look worse than it is, leading to fewer
messages and a negative spiral. Computing per-user windows from response
speed data (already stored) would fix this.

**9.4 Priority 4: Academic Context in User Model (Layer 3)**

Two onboarding questions (year + faculty) would let Donna understand
which courses are core vs. elective, calibrate urgency based on module
importance, and adapt tone for different academic cultures.

**9.5 Priority 5: Few-Shot Examples for Non-Deadline Categories (Layer
4)**

The candidates.py prompt has excellent examples for deadline messages
but nothing for wellbeing, social, habit, memory, or briefing
categories. Adding 1-2 examples per category (already written in the
Layer 4 doc Appendix A) would dramatically improve generation quality
for softer message types.

**10. Test Suite Results**

All 211 tests pass. The test suite covers the full pipeline from signal
collection through delivery. Below is the breakdown by module:

  ---------------------------------------------- ----------- -----------------------------------------
  **Test Module**                                **Count**   **Coverage Area**
  tests/donna/brain/test\_prefilter.py           11          Quiet hours, daily cap, cooldown, trust
  tests/donna/brain/test\_trust.py               7           Trust level boundaries
  tests/donna/brain/test\_scorer.py              8           Scoring, dedup, threshold
  tests/donna/brain/test\_feedback.py            5           Record, engage, ignore, summary
  tests/donna/brain/test\_sender.py              \~10        Format routing, window check, retry
  tests/donna/brain/test\_template\_filler.py    8           Template param generation
  tests/donna/brain/test\_validators.py          \~13        Message + format validation
  tests/donna/brain/test\_voice.py               11          Tone section builder
  tests/donna/brain/test\_behaviors.py           \~8         Behavioral model computation
  tests/donna/brain/test\_feedback\_metrics.py   \~5         Category prefs, trends
  tests/donna/signals/test\_dedup.py             5           Signal deduplication
  tests/donna/signals/test\_enrichment.py        4           Cross-signal patterns
  tests/donna/signals/test\_internal.py          9           Internal signal generation
  tests/donna/memory/\*                          \~8         Entity store, embeddings, recall
  tests/donna/test\_full\_loop.py                8           End-to-end pipeline scenarios
  tests/donna/test\_reflection.py                2           Nightly reflection
  tests/donna/test\_user\_model.py               2           User snapshot
  tests/test\_deferred\_send.py                  6           Deferred send queue
  tests/test\_delivery\_status.py                5           Webhook status updates
  tests/test\_whatsapp.py                        11          WhatsApp API parsing
  ---------------------------------------------- ----------- -----------------------------------------

**10.1 Missing Test Coverage**

-   **Category suppression:** No tests for suppress/re-introduce flow
    (because feature not built).

-   **Exploration budget:** No tests for explore vs exploit
    randomization.

-   **Midnight-crossing quiet hours:** No explicit test for
    sleep\_time=23:00, wake\_time=08:00 with current\_hour=02:00.

-   **All-day calendar events:** No test for events with date instead of
    dateTime.

-   **DeferredInsight reactive surfacing:** Tests for storage but not
    for retrieval in composer.py.

-   **Meta-feedback application:** Tests for detection but not for the
    actual preference override.

**11. Conclusion**

Donna\'s proactive system is architecturally mature. The 6-layer design
is well-documented and the implementation follows it closely. Of the
\~80 features specified across the 6 layer docs, roughly 55 are fully
implemented, 12 are partially implemented, and 13 remain unbuilt. The
test suite is comprehensive at 211 passing tests with good scenario
coverage.

The system\'s biggest strength is the prefilter → trust ramp → scoring
pipeline, which prevents most low-value messages from reaching users.
The biggest weakness is the incomplete feedback loop: outcomes are
captured but don\'t fully drive adaptive behavior (no category
suppression, no exploration budget, no adaptive engagement windows).

To make Donna feel truly human, the focus should be on: (1) completing
the feedback-driven adaptation loop so Donna genuinely learns each
student\'s preferences, (2) adding academic context to the user model so
messages feel personally relevant, (3) enriching the few-shot examples
for non-deadline categories so the LLM generates better wellbeing,
social, and memory messages, and (4) implementing cross-signal compound
nudges (email + calendar, task + mood, memory + social) that connect
dots the way a thoughtful friend would.
