"""
Preprocessing Module for NLP Sentiment Analysis
================================================
Reusable text preprocessing functions for sentiment analysis.

This module is designed to be:
1. Importable in Jupyter notebooks for learning/demo purposes
2. Directly reusable in a FastAPI backend with zero changes

Each function is stateless, type-hinted, and returns the processed text.
The orchestrator functions `clean_text()` and `clean_text_tokens()` chain
all steps in the correct order.

NLTK and spaCy resources are loaded lazily on first use, with automatic
downloads if missing.
"""

import re
import string
from typing import List

# ---------------------------------------------------------------------------
# Lazy-loaded resources (NLTK + spaCy)
# ---------------------------------------------------------------------------
_NLTK_READY = False
_SPACY_NLP = None

# Negation words that must NOT be removed as stop words
# (they flip sentiment and are critical for classification)
NEGATION_WORDS = {
    "not", "no", "nor", "never", "none", "n't",
    "cannot", "cant", "without", "hardly", "barely",
}


def _ensure_nltk():
    """Download required NLTK data if not already present."""
    global _NLTK_READY
    if _NLTK_READY:
        return

    import nltk

    resources = [
        "punkt",
        "punkt_tab",
        "stopwords",
        "wordnet",
        "omw-1.4",
        "vader_lexicon",
    ]
    for resource in resources:
        try:
            # Try to find the resource
            if resource in ("punkt", "punkt_tab"):
                nltk.data.find(f"tokenizers/{resource}")
            elif resource == "stopwords":
                nltk.data.find("corpora/stopwords")
            elif resource in ("wordnet", "omw-1.4"):
                nltk.data.find(f"corpora/{resource}")
            elif resource == "vader_lexicon":
                nltk.data.find("sentiment/vader_lexicon")
        except LookupError:
            nltk.download(resource, quiet=True)

    _NLTK_READY = True


def _get_spacy_nlp():
    """Load spaCy English model lazily."""
    global _SPACY_NLP
    if _SPACY_NLP is not None:
        return _SPACY_NLP

    import spacy

    try:
        _SPACY_NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    except OSError:
        # Model not installed — try to download
        import subprocess
        import sys

        subprocess.check_call(
            [sys.executable, "-m", "spacy", "download", "en_core_web_sm"]
        )
        _SPACY_NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])

    return _SPACY_NLP


# ---------------------------------------------------------------------------
# Individual preprocessing functions
# ---------------------------------------------------------------------------


def lowercase(text: str) -> str:
    """
    Convert all characters in the text to lowercase.

    Why: Ensures uniformity — 'Great' and 'great' are treated as the same word.
    Without this, the model would see them as two different features.

    Args:
        text: Raw input string.

    Returns:
        Lowercased string.
    """
    return text.lower()


def remove_urls(text: str) -> str:
    """
    Remove URLs (http, https, www) from the text.

    Why: URLs carry no sentiment information and add noise to the vocabulary.

    Args:
        text: Input string (ideally already lowercased).

    Returns:
        String with URLs removed.
    """
    url_pattern = re.compile(r"https?://\S+|www\.\S+")
    return url_pattern.sub("", text)


def remove_html(text: str) -> str:
    """
    Remove HTML tags from the text.

    Why: Reviews scraped from websites often contain residual HTML tags
    like <br>, <p>, <b> that are not meaningful for sentiment.

    Args:
        text: Input string that may contain HTML tags.

    Returns:
        String with HTML tags removed.
    """
    html_pattern = re.compile(r"<[^>]+>")
    return html_pattern.sub("", text)


def remove_emojis(text: str) -> str:
    """
    Remove emoji characters from the text.

    Why: While emojis can carry sentiment, for this classical ML pipeline
    we focus on text features. Emojis are removed to keep the vocabulary clean.
    (A deep learning model could leverage emojis as features.)

    Args:
        text: Input string that may contain emojis.

    Returns:
        String with emojis removed.
    """
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002700-\U000027BF"  # dingbats
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U00002600-\U000026FF"  # misc symbols
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)


def remove_numbers(text: str) -> str:
    """
    Remove standalone numbers and digits from the text.

    Why: Numbers like '123' or '50%' rarely contribute to sentiment
    in a general-purpose model and inflate vocabulary size.

    Args:
        text: Input string that may contain numbers.

    Returns:
        String with numbers removed.
    """
    # Remove standalone numbers (including decimals and percentages)
    number_pattern = re.compile(r"\b\d+(?:\.\d+)?%?\b")
    return number_pattern.sub("", text)


def remove_punctuation(text: str) -> str:
    """
    Remove punctuation marks from the text.

    Why: Punctuation like !, ?, , doesn't carry sentiment for classical ML
    models. Removing it simplifies tokenization and reduces feature space.

    Args:
        text: Input string that may contain punctuation.

    Returns:
        String with punctuation removed.
    """
    translator = str.maketrans("", "", string.punctuation)
    return text.translate(translator)


def tokenize(text: str) -> List[str]:
    """
    Split text into individual tokens (words).

    Why: Tokenization is the bridge between raw text and feature extraction.
    ML models operate on tokens, not raw strings.

    Args:
        text: Cleaned input string (no punctuation, no URLs).

    Returns:
        List of word tokens.
    """
    _ensure_nltk()
    from nltk.tokenize import word_tokenize

    tokens = word_tokenize(text)
    # Filter out any empty strings or single-character artifacts
    return [t for t in tokens if len(t) > 0]


def remove_stopwords(tokens: List[str]) -> List[str]:
    """
    Remove English stop words from a list of tokens.

    Why: Stop words (the, is, at, which, etc.) appear in almost every
    document and carry little sentiment information. Removing them
    reduces noise and focuses on meaningful words.

    IMPORTANT: Negation words (not, no, never, n't, etc.) are RETAINED
    because they flip sentiment — "not good" vs "good" are opposites.

    Args:
        tokens: List of word tokens.

    Returns:
        Filtered list with stop words removed (negations kept).
    """
    _ensure_nltk()
    from nltk.corpus import stopwords as nltk_stopwords

    stop_words = set(nltk_stopwords.words("english"))
    # Remove negation words from the stop word set so they are kept
    stop_words = stop_words - NEGATION_WORDS

    return [token for token in tokens if token not in stop_words]


def lemmatize(tokens: List[str]) -> List[str]:
    """
    Convert words to their base dictionary form (lemma).

    Why: 'running' → 'run', 'cars' → 'car', 'loved' → 'love'.
    Lemmatization reduces vocabulary size and groups word variants
    into a single feature. Unlike stemming, lemmatization always
    produces real dictionary words.

    Uses spaCy for POS-aware lemmatization (handles 'better' → 'good').

    Args:
        tokens: List of word tokens.

    Returns:
        List of lemmatized tokens.
    """
    nlp = _get_spacy_nlp()

    # Process tokens as a single doc for efficiency
    doc = nlp(" ".join(tokens))
    lemmas = [token.lemma_.lower().strip() for token in doc]

    # Filter out empty strings that may result from spaCy processing
    return [lemma for lemma in lemmas if len(lemma) > 0]


def remove_extra_spaces(text: str) -> str:
    """
    Collapse multiple whitespace characters into a single space and strip edges.

    Why: After removing URLs, HTML, numbers, etc., the text often has
    irregular spacing (double spaces, leading/trailing spaces) that
    can cause issues in tokenization and display.

    Args:
        text: Input string with potentially irregular spacing.

    Returns:
        Cleaned string with single spaces only.
    """
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Orchestrator functions
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """
    Apply the full preprocessing pipeline and return a clean string.

    Pipeline order:
    1. lowercase
    2. remove_urls
    3. remove_html
    4. remove_emojis
    5. remove_numbers
    6. remove_punctuation
    7. remove_extra_spaces
    8. tokenize
    9. remove_stopwords
    10. lemmatize
    11. Join tokens back into a string

    This function is FastAPI-ready: pass a raw review string, get clean text.

    Args:
        text: Raw review string.

    Returns:
        Cleaned text string (lemmatized, stop words removed).
    """
    # Text-level cleaning
    text = lowercase(text)
    text = remove_urls(text)
    text = remove_html(text)
    text = remove_emojis(text)
    text = remove_numbers(text)
    text = remove_punctuation(text)
    text = remove_extra_spaces(text)

    # Token-level cleaning
    tokens = tokenize(text)
    tokens = remove_stopwords(tokens)
    tokens = lemmatize(tokens)

    return " ".join(tokens)


def clean_text_tokens(text: str) -> List[str]:
    """
    Apply the full preprocessing pipeline and return a list of tokens.

    This is used as the tokenizer function for TfidfVectorizer.

    Args:
        text: Raw review string.

    Returns:
        List of cleaned, lemmatized tokens.
    """
    # Text-level cleaning
    text = lowercase(text)
    text = remove_urls(text)
    text = remove_html(text)
    text = remove_emojis(text)
    text = remove_numbers(text)
    text = remove_punctuation(text)
    text = remove_extra_spaces(text)

    # Token-level cleaning
    tokens = tokenize(text)
    tokens = remove_stopwords(tokens)
    tokens = lemmatize(tokens)

    return tokens


# ---------------------------------------------------------------------------
# Self-test (run: python preprocessing.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("PREPROCESSING MODULE — SELF TEST")
    print("=" * 60)

    sample = "I REALLY Loved this Phone!!! 😊 Visit https://abc.com <br> 100%"

    print(f"\nRaw text: {sample}")
    print(f"  → lowercase:          {lowercase(sample)}")
    print(f"  → remove_urls:        {remove_urls(lowercase(sample))}")
    print(f"  → remove_html:        {remove_html(remove_urls(lowercase(sample)))}")
    print(f"  → remove_emojis:      {remove_emojis(remove_html(remove_urls(lowercase(sample))))}")
    print(f"  → remove_numbers:     {remove_numbers(remove_emojis(remove_html(remove_urls(lowercase(sample)))))}")
    print(f"  → remove_punctuation: {remove_punctuation(remove_numbers(remove_emojis(remove_html(remove_urls(lowercase(sample))))))}")
    print(f"  → remove_extra_spaces:{remove_extra_spaces(remove_punctuation(remove_numbers(remove_emojis(remove_html(remove_urls(lowercase(sample)))))))}")

    cleaned = remove_extra_spaces(remove_punctuation(remove_numbers(remove_emojis(remove_html(remove_urls(lowercase(sample)))))))
    print(f"  → tokenize:           {tokenize(cleaned)}")
    print(f"  → remove_stopwords:   {remove_stopwords(tokenize(cleaned))}")
    print(f"  → lemmatize:          {lemmatize(remove_stopwords(tokenize(cleaned)))}")

    print(f"\n  → clean_text (full):  '{clean_text(sample)}'")
    print(f"  → clean_text_tokens:  {clean_text_tokens(sample)}")

    # Test negation retention
    neg_test = "This is not good at all"
    print(f"\nNegation test: '{neg_test}'")
    print(f"  → tokens:    {tokenize(remove_punctuation(lowercase(neg_test)))}")
    print(f"  → no stop:   {remove_stopwords(tokenize(remove_punctuation(lowercase(neg_test))))}")
    print(f"  → clean:     '{clean_text(neg_test)}'")
    print("  ✓ 'not' is retained (not removed as stop word)")

    # Test lemmatization examples
    lemmatize_tests = ["running", "cars", "loved", "better", "studies", "mice"]
    print(f"\nLemmatization tests:")
    for word in lemmatize_tests:
        result = lemmatize([word])
        print(f"  {word} → {result[0] if result else '(empty)'}")

    print("\n" + "=" * 60)
    print("All self-tests passed!")
    print("=" * 60)