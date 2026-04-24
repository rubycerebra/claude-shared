"""Mental health keyword detection — extracted from claude_core.diarium_ingest."""
from __future__ import annotations

import re
import sys


def find_mental_health_keywords(text, use_ai=False):
    """Find mental health keywords with categorisation across 7 domains.

    AI-FIRST PATTERN:
    - When use_ai=True: Tries AI-based keyword/theme detection first, falls back to heuristic
    - When use_ai=False (default): Uses heuristic keyword matching only

    Returns a list of context strings for backwards compatibility.
    """
    if use_ai and text and len(text) > 50:
        try:
            from ..config import build_runtime_config
            scripts_dir = str(build_runtime_config().paths.scripts_dir)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from shared.ai_service import try_ai_analysis

            ai_prompt = f"""Extract mental health themes (anxiety_stress/mood_energy/relationships/therapy_growth/adhd_executive/self_worth/fitness_body) from this text. Max 15 items.

{text[:2000]}

JSON: {{"keywords": [{{"category": "anxiety_stress", "context": "direct quote up to 200 chars"}}]}}"""

            analysis = try_ai_analysis(
                ai_prompt,
                fallback_fn=lambda: None,
                label="mental_health_keywords",
                max_tokens=512
            )

            if analysis["path"] == "ai" and analysis["result"]:
                ai_data = analysis["result"]
                keywords = ai_data.get("keywords", [])
                if keywords:
                    return [k.get("context", "") for k in keywords[:15] if k.get("context")]
        except Exception:
            pass  # Fall through to heuristic

    categories = {
        'anxiety_stress': [
            'anxiety', 'anxious', 'worry', 'worried', 'stress', 'stressed',
            'overwhelm', 'overwhelmed', 'panic', 'panicking', 'fear', 'scared',
            'dread', 'tense', 'nervous', 'on edge', 'racing thoughts',
            'intrusive', 'ruminate', 'ruminating', 'overthinking', 'catastroph',
            'what if', 'cant stop thinking', "can't stop thinking",
        ],
        'mood_energy': [
            'depressed', 'depression', 'sad', 'upset', 'low', 'down',
            'tired', 'exhausted', 'drained', 'numb', 'empty', 'flat',
            'hopeless', 'pointless', 'crying', 'tearful', 'heavy',
            'unmotivated', 'no energy', "can't be bothered",
        ],
        'relationships': [
            'janna', 'wife', 'fight', 'argument', 'conflict', 'disconnect',
            'lonely', 'alone', 'isolated', 'misunderstood', 'rejected',
            'boundary', 'boundaries', 'people pleasing', 'resentment',
            'victim', 'rescuer', 'persecutor', 'drama triangle',
            'codependent', 'attachment', 'abandonment',
        ],
        'therapy_growth': [
            'therapy', 'therapist', 'samantha', 'session', 'cbt', 'coping',
            'self compassion', 'self-compassion', 'healing', 'progress',
            'breakthrough', 'realisation', 'realization', 'pattern',
            'trigger', 'grounding', 'mindful', 'acceptance',
            'inner critic', 'self talk', 'self-talk', 'schema',
        ],
        'adhd_executive': [
            'adhd', 'autism', 'autistic', 'executive function', 'focus',
            'distracted', 'procrastinat', 'avoidance', 'avoiding',
            'time blind', 'hyperfocus', 'paralysis', 'decision fatigue',
            'object permanence', 'forgot', 'forgotten', 'lost track',
            'sensory', 'overstimulat', 'shutdown', 'meltdown',
            'masking', 'burnout', 'spoon', 'capacity',
        ],
        'self_worth': [
            'not good enough', 'imposter', 'failure', 'worthless',
            'shame', 'ashamed', 'guilt', 'guilty', 'embarrass',
            'compare', 'comparing', 'should be', 'behind',
            'everyone else', 'other people', 'successful',
            'fraud', 'deserve', 'undeserving', 'doubt myself',
        ],
        'fitness_body': [
            'yoga', 'weights', 'lifting', 'exercise', 'workout', 'walk',
            'dog walk', 'running', 'gym', 'stretch', 'body', 'pain',
            'sleep', 'insomnia', 'restless', 'appetite', 'eating',
            'headache', 'tension', 'energy', 'strong', 'movement',
        ],
    }

    found = []
    text_lower = text.lower()
    sentences = re.split(r'[.!?\n]+', text)

    seen_sentences = set()
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in text_lower:
                for sentence in sentences:
                    if keyword in sentence.lower():
                        cleaned = ' '.join(sentence.split()).strip()
                        if cleaned and len(cleaned) > 15 and cleaned not in seen_sentences:
                            seen_sentences.add(cleaned)
                            found.append({
                                'category': category,
                                'keyword': keyword,
                                'context': cleaned[:200],
                            })

    return [f['context'] for f in found[:15]]


def find_mental_health_keywords_categorised(text):
    """Return categorised keyword hits with category counts.

    Returns: {'categories_hit': {'anxiety_stress': 3, ...}, 'insights': [...]}
    """
    categories = {
        'anxiety_stress': [
            'anxiety', 'anxious', 'worry', 'worried', 'stress', 'stressed',
            'overwhelm', 'overwhelmed', 'panic', 'panicking', 'fear', 'scared',
            'dread', 'tense', 'nervous', 'on edge', 'racing thoughts',
            'intrusive', 'ruminate', 'ruminating', 'overthinking', 'catastroph',
        ],
        'mood_energy': [
            'depressed', 'depression', 'sad', 'upset', 'low', 'down',
            'tired', 'exhausted', 'drained', 'numb', 'empty', 'flat',
            'hopeless', 'pointless', 'crying', 'tearful', 'heavy',
        ],
        'relationships': [
            'janna', 'wife', 'fight', 'argument', 'conflict', 'disconnect',
            'lonely', 'alone', 'isolated', 'misunderstood', 'rejected',
            'boundary', 'boundaries', 'people pleasing', 'resentment',
            'victim', 'rescuer', 'persecutor', 'drama triangle',
        ],
        'therapy_growth': [
            'therapy', 'therapist', 'samantha', 'session', 'cbt', 'coping',
            'self compassion', 'healing', 'progress', 'breakthrough',
            'realisation', 'realization', 'pattern', 'trigger', 'grounding',
        ],
        'adhd_executive': [
            'adhd', 'autism', 'autistic', 'executive function', 'focus',
            'distracted', 'procrastinat', 'avoidance', 'avoiding',
            'time blind', 'hyperfocus', 'paralysis', 'decision fatigue',
            'object permanence', 'sensory', 'overstimulat', 'shutdown',
            'masking', 'burnout',
        ],
        'self_worth': [
            'not good enough', 'imposter', 'failure', 'worthless',
            'shame', 'ashamed', 'guilt', 'guilty', 'embarrass',
            'compare', 'comparing', 'should be', 'behind',
            'fraud', 'deserve', 'doubt myself',
        ],
        'fitness_body': [
            'yoga', 'weights', 'lifting', 'exercise', 'workout', 'walk',
            'dog walk', 'running', 'gym', 'stretch', 'sleep', 'insomnia',
            'restless', 'appetite', 'eating', 'headache', 'energy',
        ],
    }

    text_lower = text.lower()
    sentences = re.split(r'[.!?\n]+', text)
    categories_hit = {}
    insights = []
    seen = set()

    for category, keywords in categories.items():
        hits = 0
        for keyword in keywords:
            if keyword in text_lower:
                hits += 1
                for sentence in sentences:
                    if keyword in sentence.lower():
                        cleaned = ' '.join(sentence.split()).strip()
                        if cleaned and len(cleaned) > 15 and cleaned not in seen:
                            seen.add(cleaned)
                            insights.append({
                                'category': category,
                                'keyword': keyword,
                                'context': cleaned[:200],
                            })
        if hits > 0:
            categories_hit[category] = hits

    return {'categories_hit': categories_hit, 'insights': insights[:20]}
