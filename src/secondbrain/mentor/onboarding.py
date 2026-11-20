"""Phase 0: Vikram gets to know Daksh. Eight short question groups, asked one at a time as he answers."""

from __future__ import annotations

GROUPS: tuple[tuple[str, str], ...] = (
    ("coachable",
     "Before anything else: are you coachable? I mean it. Will you tell me the truth, do what you say you'll do, and tell "
     "me straight away when you bristle at something I say?"),
    ("building",
     "What are you building right now, and why? Skip the polished version, give me the real reason. And what does 'made it' "
     "look like in three years, in actual numbers?"),
    ("avoiding",
     "What's the one thing you know you should be doing and keep not doing? The thing that makes your stomach tighten."),
    ("history",
     "What have you already tried about that, and what happened each time? And has anyone helped you before? What did they do "
     "that actually worked?"),
    ("pressure",
     "Money and family. What's the pressure at home, what do you spend in a month, and does anyone expect something specific "
     "from you after graduation?"),
    ("routine",
     "Walk me through a normal day. When do you sleep, when do you do your best work, and where does the time actually go?"),
    ("distractions",
     "What pulls you off track most: people, games, YouTube, a girl, family stuff, your own mood? Give me the honest list, "
     "I'm not here to judge, I need the real picture."),
    ("numbers",
     "Last two. How many job applications a week can you honestly send beside your studies? And is there one person, a friend "
     "or a senior engineer, who could see your weekly numbers?"),
)

TOTAL = len(GROUPS)


def group_name(step: int) -> str:
    return GROUPS[step][0]


def group_text(step: int) -> str:
    return GROUPS[step][1]
