"""Small shared coercion/format helpers for dashboard generation."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime


# ── Canonical ta-dah theme keywords ──────────────────────────────────
# Single source of truth. Both generate-dashboard.py and data_collector.py
# import from here. OrderedDict: first match wins (more specific themes first).

TADAH_THEME_KEYWORDS = OrderedDict([
    ("emotional_growth", [
        # Perseverance, accountability, vulnerability
        "persever", "remorse", "accountab", "apologi",
        "forgave", "bounced back", "pushed through", "kept going", "didn't give up",
        "vulnerab", "brave", "proud", "overcame", "faced my",
        "admitted", "reflected", "grew", "growth",
        # Emotional breakthroughs
        "let go", "moved on", "forgave myself", "self-compassion",
        "set a boundary", "said no", "stood up for", "spoke up",
        "asked for what", "opened up", "told them", "was honest about",
        # Therapy / inner work
        "therapy", "therapist", "therapy session", "realised", "realized",
        "trigger", "awareness", "mindful",
        "processed", "worked through", "sat with",
    ]),
    ("family", [
        "family", "wife", "daughter", "kids", "janna", "girls", "mum", "my dad",
        "museum", "outing", "day out", "nice time with",
        "baby", "toddler", "son", "brother", "sister", "niece", "nephew",
        # Quality time activities
        "played with", "read to", "bedtime stor", "bath time", "school run",
        "picked up from", "dropped off", "playground", "soft play",
        "baked with", "cooked with", "movie night", "game night", "board game",
        "cuddl", "snuggl", "tucked in", "kissed goodnight",
        "date night", "evening together", "quality time",
    ]),
    ("admin", [
        # Organisation / planning
        "organis", "schedule", "arrange",
        "booked", "booking", "appointment", "reserved", "confirmed", "cancelled",
        "rescheduled", "signed up", "registered", "enrolled",
        # Digital / tech admin
        "claude", "dashboard", "api", "parsing",
        "configured", "installed", "backup",
        "password", "subscription", "renewed",
        # Life admin
        "paid", "payment", "invoice", "tax", "refund", "claim",
        "paperwork", "document", "filed", "submitted",
        "returned item", "exchanged", "ordered", "delivered",
        "phone call", "rang", "chased", "followed up", "complaint",
        "insurance", "mortgage", "direct debit",
        # Planning
        "planned", "prepared", "researched", "compared",
        "made a list", "prioriti", "budget",
    ]),
    ("social", [
        "friend", "adam",
        # Communication
        "messaged", "replied", "reached out", "spoke to", "texted", "called",
        "caught up", "checked in", "coffee with", "drink with", "met up",
        "visited", "had over", "hosted", "invite",
        # Community
        "club", "meetup", "gathering", "party",
        "neighbour", "neighbor",
    ]),
    ("creative", [
        "cinema", "photo", "creative", "music",
        # Media creation
        "drew", "sketch", "paint", "design", "edited video", "video",
        "podcast", "composing", "lyric", "poem",
        "blog", "article", "newsletter",
        # Media consumption (intentional)
        "watched", "listened to", "audiobook", "documentary",
        "gallery", "exhibition", "theatre", "theater", "gig", "concert",
        "album", "playlist",
        # Learning / hobby
        "learned", "learnt", "tutorial", "hobby",
    ]),
    ("self_care", [
        # Physical activity
        "yoga", "walked", "walking", "weights", "exercise", "meditat", "stretch", "gym",
        "went for a run", "running", "jogging", "swimming", "cycling", "bike", "steps",
        "pilates", "boxing", "martial", "climbing",
        # Nutrition
        "breakfast", "healthy meal", "ate well", "cooked healthy", "meal prep",
        "drank water", "hydrat", "vitamins", "supplements", "protein",
        "fruit", "smoothie",
        # Grooming / hygiene
        "shower", "teeth", "dressed", "haircut", "barber",
        "shave", "skincare", "grooming", "moisturis",
        # Rest / sleep
        "nap", "slept", "got up on time", "woke up",
        "routine", "bed on time", "wind down", "screen off",
        # Medical / health
        "medication", "meds", "doctor", "gp", "dentist", "optician",
        "prescription", "blood test", "checkup",
        # Mental health / emotional regulation
        "diary", "journal", "coco", "regulated", "calm",
        "breathed", "coped", "anxiety",
        "didn't snap", "got through", "hard day",
        "asked for help", "deep breath", "grounding",
        "sensory", "stim", "decompress", "downtime", "alone time",
        # Neurodivergent wins
        "remembered to", "didn't forget", "on time", "stuck to",
        "followed through", "didn't avoid",
        "switched task", "executive function",
    ]),
    ("household", [
        # Cleaning
        "clean", "tidy", "tidied", "laundry", "dishes", "hoover", "household",
        "extractor", "sweep", "mop", "vacuum", "dusting",
        "bins", "scrub", "bleach", "descale", "declutter",
        "wiped", "organised cupboard", "sorted drawer",
        # Cooking
        "cook", "burrito", "dinner", "lunch", "made food",
        "roast", "prepped", "chopped", "recipe",
        "slow cooker", "air fryer",
        # Home maintenance
        "diy", "fixed the", "repaired", "replaced", "assembled", "built",
        "painted", "drilled", "plumbing", "wired", "bulb", "fuse",
        "shelf", "curtain", "blind",
        # Garden
        "garden", "mowed", "weeding", "planted", "compost", "hedge",
        "grass", "pruned", "repotted",
        # Errands / shopping
        "shopping", "groceries", "supermarket", "tesco", "aldi", "lidl",
        "asda", "sainsbury", "petrol", "car wash", "mot",
        # Pet care
        "vet", "fed the", "walked the",
    ]),
    ("work", [
        "went to work", "at work", "job", "apply", "application",
        "interview", "career", "sony", "bfi", "working title", "office",
        # Job search
        "cv", "cover letter", "portfolio", "linkedin", "recruiter",
        "networking", "salary", "contract", "freelance",
        "client", "meeting", "deadline", "project",
        # Freelance / professional
        "chris", "hourly", "deliverable", "brief",
        "shipped", "deployed", "launched",
        "presentation", "pitch", "proposal",
    ]),
])

TADAH_THEME_EMOJIS = {
    "work": "💼", "self_care": "🧘", "household": "🏠",
    "family": "👨‍👩‍👧", "creative": "🎬", "social": "💬",
    "health": "💪", "admin": "📋", "learning": "📚",
    "emotional_growth": "🌱",
}

# Keywords that indicate cleaning (used to prevent false self_care matches)
CLEANING_KEYWORDS = frozenset([
    "clean", "tidy", "wash", "hoover", "vacuum", "sweep", "mop", "dust", "iron",
])


def coerce_optional_int(value, min_val: int, max_val: int):
    try:
        if value is None or value == "":
            return None
        n = int(value)
    except Exception:
        return None
    if n < min_val or n > max_val:
        return None
    return n


def coerce_choice(value, allowed, *, empty_value=None):
    raw = str(value or "").strip().lower()
    return raw if raw in allowed else empty_value


def input_num_text(value, min_v, max_v) -> str:
    try:
        if value is None or value == "":
            return ""
        n = float(value)
    except Exception:
        return ""
    if n < float(min_v) or n > float(max_v):
        return ""
    if float(n).is_integer():
        return str(int(n))
    return str(round(float(n), 1))


def end_day_status_text(state: dict) -> str:
    if not isinstance(state, dict) or not bool(state.get("done_today")):
        return "⬜ End Day not run yet."
    ran_at = str(state.get("ran_at", "")).strip()
    if ran_at:
        try:
            return f"✅ End Day already run at {datetime.fromisoformat(ran_at).strftime('%H:%M')}."
        except Exception:
            pass
    return "✅ End Day already run today."
