import re
import unicodedata
from difflib import SequenceMatcher

STOPWORDS = {
    # pt
    "para", "como", "porque", "por", "que", "uma", "um", "dos", "das", "nos", "nas", "com", "sem", "sobre", "mais",
    "menos", "isso", "esse", "essa", "este", "esta", "você", "voce", "seu", "sua", "ele", "ela", "eles", "elas",
    "qual", "quais", "quando", "onde", "muito", "muita", "também", "tambem", "ainda", "agora", "primeiro", "depois",
    "entre", "até", "ate", "são", "sao", "foi", "ser", "tem", "têm", "pela", "pelo", "pelos", "pelas", "aos", "num",
    # en
    "the", "and", "for", "with", "that", "this", "what", "why", "how", "when", "where", "which", "from", "into",
    "your", "you", "are", "was", "were", "have", "has", "had", "about", "there", "their", "they", "them", "then",
    "than", "just", "more", "most", "some", "will", "would", "could", "should", "ever", "wondered", "first", "now",
}

LANGUAGE_NAME = {"pt-BR": "português do Brasil", "en-US": "American English", "en-GB": "British English"}


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in folded if not unicodedata.combining(char))


def keywords(text: str, limit: int = 6) -> list[str]:
    seen: list[str] = []
    for word in re.findall(r"[\wÀ-ÿ]+", text):
        token = word.lower()
        if len(token) < 4 or token in STOPWORDS or token.isdigit() or token in seen:
            continue
        seen.append(token)
    return sorted(seen, key=len, reverse=True)[:limit]


def overlap_score(query: str, text: str) -> float:
    wanted = {normalize(word) for word in keywords(query, 12)}
    if not wanted:
        return 0.0
    have = {normalize(word) for word in re.findall(r"[\wÀ-ÿ]+", text)}
    return len(wanted & have) / len(wanted)


def similar(a: str, b: str) -> float:
    """Character similarity, or word overlap so reordered titles ("Destiny 1 queda") still count as duplicates."""
    words_a = {normalize(word) for word in keywords(a, 20)}
    words_b = {normalize(word) for word in keywords(b, 20)}
    shared = words_a & words_b
    # One shared word is not enough: "Halo 2" and "Halo 3" are different videos.
    overlap = len(shared) / len(words_a | words_b) if len(shared) >= 2 else 0.0
    return max(SequenceMatcher(None, normalize(a), normalize(b)).ratio(), overlap)


def sentences(text: str, limit: int = 2) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [part for part in parts if len(part) > 30][:limit]
