# Skill: Recipe Pipeline

## When to use
Working on recipe ingestion from PDFs, embedding generation, FAISS index, or semantic search.

## Pipeline overview
```
PDF files (from dietitians)
    ↓ scripts/seed_recipes.py
Extract text (pdfplumber / PyMuPDF)
    ↓
Anthropic Haiku parses each recipe → structured JSON
    ↓
{name, ingredients, instructions, kcal, protein, carbs, fat, prep_time, tags}
    ↓
Store in DynamoDB: PK=RECIPES, SK=RECIPE#001
    ↓
Generate embeddings (Anthropic voyage-3-lite or sentence-transformers)
    ↓
Build FAISS index → upload to S3
```

## Recipe JSON schema
```json
{
  "id": "recipe_001",
  "name": "Kurczak z ryżem i brokułami",
  "ingredients": ["500g piersi kurczaka", "200g ryżu", "300g brokułów"],
  "instructions": "1. Ugotuj ryż...",
  "kcal": 520,
  "protein": 45,
  "carbs": 52,
  "fat": 12,
  "prep_time": 25,
  "tags": ["high-protein", "meal-prep", "obiad"],
  "source": "pdf_dietician_anna.pdf"
}
```

## FAISS in Lambda
- Index file stored in S3: `s3://syncbody-data/faiss/recipes.index`
- Metadata JSON: `s3://syncbody-data/faiss/recipes_meta.json`
- Lambda loads both on cold start (3-5s for ~1000 recipes, ~6MB index)
- Search: embed query → FAISS nearest neighbors → return top N recipes

## MVP shortcut
For MVP (< 100 recipes): skip FAISS entirely. Pass all recipes as JSON in the AI advisor prompt. Haiku 4.5 has 200K context — 100 recipes fit easily. Add FAISS when recipes > 500.

## PDF parsing tips
- Use `pdfplumber` for text-heavy PDFs (recipe books)
- Use `PyMuPDF (fitz)` for PDFs with complex layouts
- Send extracted text to Haiku in batches of 5-10 recipes per call
- Prompt: "Wyparsuj każdy przepis z tekstu. Zwróć JSON array z polami: name, ingredients (array), instructions, kcal, protein, carbs, fat, prep_time, tags. Jeśli brakuje danych o makro, estymuj na podstawie składników."
