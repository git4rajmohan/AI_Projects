"""
Dataset Generator for NLP Sentiment Analysis Demo
==================================================
Generates a balanced ~2,000-row CSV dataset with 3 sentiment classes
(Positive, Neutral, Negative) using template-based generation.

Deliberately injects noise (URLs, emojis, HTML tags, numbers, extra spaces,
ALL CAPS) into ~15% of reviews so every preprocessing function has something
to clean.

Output: data/reviews.csv  (columns: Review, Sentiment)
"""

import csv
import random
import os

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
random.seed(42)

# ---------------------------------------------------------------------------
# Template pools
# Each template uses {product} placeholder which is filled from PRODUCTS list.
# ---------------------------------------------------------------------------
PRODUCTS = [
    "phone", "laptop", "headphones", "camera", "tablet", "watch",
    "speaker", "keyboard", "mouse", "monitor", "charger", "earbuds",
    "backpack", "printer", "router", "microphone", "webcam", "drone",
    "vacuum", "blender", "toaster", "microwave", "air fryer", "fan",
    "heater", "lamp", "desk", "chair", "pillow", "blanket",
]

POSITIVE_TEMPLATES = [
    "I love this {product}!",
    "Amazing {product}, highly recommend it.",
    "This {product} is fantastic and works perfectly.",
    "Best {product} I have ever bought.",
    "Really happy with this {product}.",
    "The {product} exceeded my expectations.",
    "Great quality {product} for the price.",
    "This {product} is wonderful and easy to use.",
    "I am very impressed with this {product}.",
    "The {product} is superb, five stars!",
    "Excellent {product}, fast delivery too.",
    "This {product} changed my daily routine.",
    "So pleased with this {product}.",
    "The {product} is durable and well built.",
    "Fantastic {product}, would buy again.",
    "I adore this {product}, it is beautiful.",
    "This {product} is a game changer.",
    "Brilliant {product} with great features.",
    "The {product} is worth every penny.",
    "My favorite purchase this year, this {product}.",
    "This {product} is absolutely perfect.",
    "The {product} is reliable and efficient.",
    "I am thrilled with this {product}.",
    "This {product} makes life so much easier.",
    "Outstanding {product}, top notch quality.",
    "The {product} is a delight to use.",
    "I cannot stop using this {product}.",
    "This {product} is a must have.",
    "The {product} is stylish and functional.",
    "Superb {product}, I am a happy customer.",
    "This {product} is incredible value.",
    "The {product} is fast and responsive.",
    "I am in love with this {product}.",
    "This {product} is simply the best.",
    "The {product} is a fantastic investment.",
    "This {product} is a joy to own.",
    "The {product} is sleek and modern.",
    "I am so glad I bought this {product}.",
    "This {product} is a great addition to my home.",
    "The {product} is powerful and compact.",
    "This {product} is a lifesaver.",
    "The {product} is comfortable and lightweight.",
    "I am extremely satisfied with this {product}.",
    "This {product} is a brilliant design.",
    "The {product} is a pleasure to work with.",
    "This {product} is a wonderful gift.",
    "The {product} is a solid purchase.",
    "I am blown away by this {product}.",
    "This {product} is a total winner.",
    "The {product} is a great find.",
    "I am loving this {product} so much.",
    "This {product} is a real bargain.",
    "The {product} is a fantastic product overall.",
    "I am very happy with this {product}.",
    "This {product} is a great value for money.",
    "The {product} is a top quality item.",
    "I am really enjoying this {product}.",
    "This {product} is a great buy.",
    "The {product} is a wonderful experience.",
    "I am very pleased with this {product}.",
    "This {product} is a great choice.",
    "The {product} is a fantastic deal.",
    "I am very impressed by this {product}.",
    "This {product} is a great investment.",
    "The {product} is a superb choice.",
]

NEUTRAL_TEMPLATES = [
    "The {product} is okay, nothing special.",
    "Average quality {product}, does the job.",
    "This {product} is decent but not great.",
    "The {product} works fine for basic needs.",
    "It is an ordinary {product}.",
    "The {product} is neither good nor bad.",
    "This {product} is acceptable for the price.",
    "The {product} is mediocre at best.",
    "This {product} is just standard.",
    "The {product} is fine but could be better.",
    "This {product} is nothing to write home about.",
    "The {product} is a basic model.",
    "This {product} is average in every way.",
    "The {product} is passable but unremarkable.",
    "This {product} is just okay.",
    "The {product} is functional but plain.",
    "This {product} is a middle of the road option.",
    "The {product} is adequate for everyday use.",
    "This {product} is neither impressive nor terrible.",
    "The {product} is a so so purchase.",
    "This {product} is a fair deal.",
    "The {product} is a standard offering.",
    "This {product} is a typical {product}.",
    "The {product} is a reasonable choice.",
    "This {product} is a common model.",
    "The {product} is a forgettable item.",
    "This {product} is a plain {product}.",
    "The {product} is a simple device.",
    "This {product} is a modest purchase.",
    "The {product} is an unremarkable {product}.",
    "This {product} is a serviceable option.",
    "The {product} is a competent but basic item.",
    "This {product} is a vanilla version.",
    "The {product} is a run of the mill {product}.",
    "This {product} is a forgettable experience.",
    "The {product} is a passable product.",
    "This {product} is a middle tier option.",
    "The {product} is a tolerable purchase.",
    "This {product} is a forgettable buy.",
    "The {product} is a forgettable model.",
    "This {product} is a forgettable device.",
    "The {product} is a forgettable item.",
    "This {product} is a forgettable thing.",
    "The {product} is a forgettable purchase.",
    "This {product} is a forgettable option.",
    "The {product} is a forgettable choice.",
    "This {product} is a forgettable deal.",
    "The {product} is a forgettable buy.",
    "This {product} is a forgettable model.",
    "The {product} is a forgettable device.",
    "This {product} is a forgettable item.",
    "The {product} is a forgettable thing.",
    "This {product} is a forgettable purchase.",
    "The {product} is a forgettable option.",
    "This {product} is a forgettable choice.",
    "The {product} is a forgettable deal.",
    "This {product} is a forgettable buy.",
    "The {product} is a forgettable model.",
    "This {product} is a forgettable device.",
    "This {product} is a forgettable item.",
    "The {product} is a forgettable thing.",
    "This {product} is a forgettable purchase.",
    "The {product} is a forgettable option.",
    "This {product} is a forgettable choice.",
    "The {product} is a forgettable deal.",
]

NEGATIVE_TEMPLATES = [
    "Terrible {product}, total waste of money.",
    "I hate this {product}.",
    "The {product} broke after one week.",
    "Worst {product} I have ever purchased.",
    "This {product} is awful and cheap.",
    "The {product} does not work as advertised.",
    "Very disappointed with this {product}.",
    "This {product} is a complete failure.",
    "The {product} is poorly made.",
    "I regret buying this {product}.",
    "This {product} is a piece of junk.",
    "The {product} stopped working immediately.",
    "This {product} is a scam, do not buy.",
    "The {product} is frustrating to use.",
    "This {product} is a huge disappointment.",
    "The {product} is overpriced and useless.",
    "This {product} is a terrible purchase.",
    "The {product} is a nightmare to set up.",
    "This {product} is a waste of time.",
    "The {product} is a letdown.",
    "This {product} is a disaster.",
    "The {product} is a flop.",
    "This {product} is a dud.",
    "The {product} is a mess.",
    "This {product} is a bust.",
    "I am very unhappy with this {product}.",
    "The {product} is a bad investment.",
    "This {product} is a poor choice.",
    "The {product} is a bad deal.",
    "This {product} is a bad buy.",
    "I am very dissatisfied with this {product}.",
    "The {product} is a bad purchase.",
    "This {product} is a bad option.",
    "The {product} is a bad model.",
    "This {product} is a bad device.",
    "I am very frustrated with this {product}.",
    "The {product} is a bad item.",
    "This {product} is a bad thing.",
    "The {product} is a bad experience.",
    "I am very annoyed with this {product}.",
    "This {product} is a bad product overall.",
    "The {product} is a bad choice overall.",
    "This {product} is a bad deal overall.",
    "The {product} is a bad buy overall.",
    "I am very upset with this {product}.",
    "This {product} is a bad purchase overall.",
    "The {product} is a bad option overall.",
    "This {product} is a bad model overall.",
    "The {product} is a bad device overall.",
    "I am very angry about this {product}.",
    "This {product} is a bad item overall.",
    "The {product} is a bad thing overall.",
    "This {product} is a bad experience overall.",
    "I am very disappointed by this {product}.",
    "This {product} is a bad product.",
    "The {product} is a bad choice.",
    "This {product} is a bad deal.",
    "The {product} is a bad buy.",
    "I am very dissatisfied by this {product}.",
    "This {product} is a bad purchase.",
    "The {product} is a bad option.",
    "This {product} is a bad model.",
    "The {product} is a bad device.",
    "I am very frustrated by this {product}.",
    "This {product} is a bad item.",
]

# ---------------------------------------------------------------------------
# Noise injection
# ---------------------------------------------------------------------------
URLS = [
    "https://abc.com",
    "http://review.example.com",
    "https://www.productlink.com/page1",
    "www.checkthis.com",
    "https://amzn.to/3xyz",
]

EMOJIS = ["😊", "😡", "😐", "👍", "👎", "⭐", "💔", "😍", "🙄", "🔥"]

HTML_TAGS = ["<br>", "<br/>", "<p>", "</p>", "<b>", "</b>", "<i>", "</i>"]

NUMBERS = ["123", "4567", "2nd", "100%", "3x", "v2.0", "50%"]


def inject_noise(text: str) -> str:
    """Inject random noise into a review to exercise preprocessing functions."""
    noise_types = []

    # Randomly pick 1-3 noise types
    num_noises = random.randint(1, 3)
    noise_types = random.sample(
        ["url", "emoji", "html", "number", "caps", "spaces"], num_noises
    )

    for noise in noise_types:
        if noise == "url":
            text = text + " Visit " + random.choice(URLS)
        elif noise == "emoji":
            text = text + " " + random.choice(EMOJIS)
        elif noise == "html":
            text = random.choice(HTML_TAGS) + " " + text + " " + random.choice(HTML_TAGS)
        elif noise == "number":
            text = text + " " + random.choice(NUMBERS)
        elif noise == "caps":
            # Capitalize a random word
            words = text.split()
            if len(words) > 2:
                idx = random.randint(0, len(words) - 1)
                words[idx] = words[idx].upper()
            text = " ".join(words)
        elif noise == "spaces":
            # Add extra spaces
            text = text.replace(" ", "  ", 2)

    return text


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def generate_dataset(
    per_class: int = 667,
    noise_ratio: float = 0.15,
    output_path: str = None,
) -> str:
    """
    Generate the sentiment dataset CSV.

    Args:
        per_class: Number of reviews per sentiment class.
        noise_ratio: Fraction of reviews to inject noise into.
        output_path: Path to save CSV. Defaults to data/reviews.csv.

    Returns:
        Path to the generated CSV file.
    """
    if output_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, "reviews.csv")

    reviews = []

    # Generate positive reviews
    for i in range(per_class):
        template = random.choice(POSITIVE_TEMPLATES)
        product = random.choice(PRODUCTS)
        review = template.format(product=product)
        if random.random() < noise_ratio:
            review = inject_noise(review)
        reviews.append((review, "Positive"))

    # Generate neutral reviews
    for i in range(per_class):
        template = random.choice(NEUTRAL_TEMPLATES)
        product = random.choice(PRODUCTS)
        review = template.format(product=product)
        if random.random() < noise_ratio:
            review = inject_noise(review)
        reviews.append((review, "Neutral"))

    # Generate negative reviews
    for i in range(per_class):
        template = random.choice(NEGATIVE_TEMPLATES)
        product = random.choice(PRODUCTS)
        review = template.format(product=product)
        if random.random() < noise_ratio:
            review = inject_noise(review)
        reviews.append((review, "Negative"))

    # Shuffle all reviews
    random.shuffle(reviews)

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Review", "Sentiment"])
        writer.writerows(reviews)

    # Print summary
    total = len(reviews)
    pos = sum(1 for _, s in reviews if s == "Positive")
    neu = sum(1 for _, s in reviews if s == "Neutral")
    neg = sum(1 for _, s in reviews if s == "Negative")

    print(f"Dataset generated: {output_path}")
    print(f"Total reviews: {total}")
    print(f"  Positive: {pos}")
    print(f"  Neutral:  {neu}")
    print(f"  Negative: {neg}")
    print(f"Noise injected into ~{noise_ratio*100:.0f}% of reviews")

    return output_path


if __name__ == "__main__":
    generate_dataset()