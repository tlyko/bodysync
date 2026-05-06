# Skill: AI Advisor

## When to use
Working on the AI advisor Lambda (daily, weekly, chat), system prompts, or LLM integration.

## Anthropic API setup
```python
import anthropic

client = anthropic.Anthropic(api_key=get_param("/bodysync/anthropic-api-key"))

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=2048,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}  # prompt caching — 90% cheaper
    }],
    messages=[{"role": "user", "content": user_context}],
)
```

## System prompt design
File: `lambda-src/ai_advisor/system_prompt.txt`

Key elements:
- Role: "Jesteś polskim dietetykiem sportowym i trenerem personalnym"
- Rules: calculate TDEE using Mifflin-St Jeor, adjust for activity, respect goal (fat_loss/muscle_gain/maintain)
- Output: always JSON with defined schema
- Language: Polish only
- Tone: motivating but factual, use concrete numbers

## Daily advisor (cron 21:00 CET)
Input context assembled from DynamoDB:
1. User PROFILE (age, height, sex, goal, preferences, excluded foods)
2. Today's HEALTH# (steps, active calories, heart rate, sleep)
3. Today's NUTRITION# (kcal consumed, protein, carbs, fat)
4. Today's WEIGHT# (if measured)
5. Today's WORKOUT# (if any workout logged)
6. Tomorrow's TRAINING# (from Google Sheets — what exercises are planned)
7. Last 7 days weight trend
8. Top 20 matching recipes from FAISS (matching target calorie range)

Output JSON schema (saved to ADVICE#date):
```json
{
  "date": "2026-05-06",
  "summary": "Polish text analyzing today...",
  "tdee": 2450,
  "target_kcal": 1950,
  "target_macros": {"protein": 156, "carbs": 195, "fat": 65},
  "tomorrow_menu": {
    "breakfast": {"recipe": "...", "kcal": 380, "protein": 32},
    "lunch": {"recipe": "...", "kcal": 520, "protein": 45},
    "dinner": {"recipe": "...", "kcal": 320, "protein": 28},
    "snack": {"recipe": "...", "kcal": 280, "protein": 28}
  },
  "tomorrow_total": {"kcal": 1500, "protein": 133, "carbs": 148, "fat": 52},
  "note": "Polish text with specific recommendations..."
}
```

## Weekly advisor (Sunday 20:00 CET)
Input: 7 days of all metrics + previous week's report
Output: trend analysis, adherence score, weight projection, recommendations in Polish

## Chat on-demand
Input: user question + profile + today's data + last 7 days
Output: free-form Polish response with concrete numbers and recipe suggestions

## Cost optimization
- System prompt (profile + rules) cached — 90% cheaper on repeated calls
- Haiku 4.5 for daily/chat ($1/$5 per MTok)
- Consider Sonnet for weekly reports (better analysis, ~$0.05 extra per week)
- JSON mode reduces output tokens
- Batch API (-50%) for weekly reports if latency acceptable
