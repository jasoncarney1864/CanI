"""Generate human-readable document titles from extracted text using LLM."""

from __future__ import annotations


def generate_title(
    extracted_text: str, *, endpoint: str, api_key: str, api_version: str, deployment: str
) -> str:
    """Call Azure OpenAI to generate a short, descriptive title from extracted document text.

    Takes the first ~2000 characters of the document as context (enough to understand
    content, not so much that it overwhelms the prompt), and asks the LLM for a concise
    title (4-8 words) that describes what the document is about.

    Falls back to "Untitled Document" if the model returns empty or the API call fails
    (title generation should never block ingestion).
    """
    from openai import AzureOpenAI

    # Take first ~2000 chars as context for title generation
    preview = extracted_text[:2000].strip()
    if not preview:
        return "Untitled Document"

    client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)

    system_prompt = """You are a document title generator. Your job is to read a short preview of a document and create a concise, descriptive title (4-8 words) that captures what the document is about.

Rules:
- Return ONLY the title text, nothing else (no quotes, no "Title:", no explanation).
- Make it specific and descriptive (not generic like "Document" or "File").
- Use title case (capitalize first letter of major words).
- Aim for 4-8 words."""

    user_prompt = f"Generate a title for this document:\n\n{preview}"

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_completion_tokens=50,
        )
        title = (response.choices[0].message.content or "").strip()
        # Clean up common wrapper patterns LLMs sometimes add
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        if title.lower().startswith("title:"):
            title = title[6:].strip()
        return title if title else "Untitled Document"
    except Exception:  # noqa: BLE001 - title generation should never break ingestion
        return "Untitled Document"
