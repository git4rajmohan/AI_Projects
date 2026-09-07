"""
Generate a self-contained userguide.html with embedded base64 images.
Run: python generate_userguide.py
"""
import base64
import os

OUTPUTS_DIR = "outputs"
HTML_FILE = "userguide.html"


def img_to_base64(path):
    """Convert an image file to a base64 data URI."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{data}"


# Load all images
images = {}
for name in ["sentiment_distribution", "confusion_matrix", "wordcloud_positive", "wordcloud_negative", "wordcloud_neutral"]:
    path = os.path.join(OUTPUTS_DIR, f"{name}.png")
    if os.path.exists(path):
        images[name] = img_to_base64(path)
        print(f"  ✓ Embedded: {name}.png ({os.path.getsize(path)/1024:.0f} KB)")
    else:
        print(f"  ✗ Missing: {name}.png")

print(f"\nGenerating {HTML_FILE}...")

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NLP Sentiment Analysis — User Guide</title>
<style>
:root {{
  --bg:#f8f9fa; --sidebar-bg:#1a2332; --sidebar-text:#b0bec5; --sidebar-active:#2ecc71;
  --content-bg:#fff; --heading:#1a2332; --accent:#2ecc71; --accent2:#3498db;
  --border:#e0e0e0; --code-bg:#f0f4f8; --code-text:#c0392b; --card-bg:#f8f9fa;
  --positive:#2ecc71; --neutral:#f39c12; --negative:#e74c3c;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif; background:var(--bg); color:#333; line-height:1.7; display:flex; min-height:100vh; }}

#sidebar {{ width:300px; min-width:300px; background:var(--sidebar-bg); color:var(--sidebar-text); position:fixed; top:0; left:0; bottom:0; overflow-y:auto; z-index:100; transition:transform 0.3s; }}
#sidebar .header {{ padding:28px 24px 20px; border-bottom:1px solid rgba(255,255,255,0.08); }}
#sidebar .header h1 {{ color:#fff; font-size:18px; font-weight:700; line-height:1.3; }}
#sidebar .header p {{ color:var(--sidebar-active); font-size:12px; margin-top:6px; text-transform:uppercase; letter-spacing:1px; }}
#sidebar nav {{ padding:12px 0; }}
#sidebar nav a {{ display:block; padding:10px 24px; color:var(--sidebar-text); text-decoration:none; font-size:14px; border-left:3px solid transparent; transition:all 0.2s; }}
#sidebar nav a:hover {{ background:rgba(255,255,255,0.05); color:#fff; border-left-color:var(--accent2); }}
#sidebar nav a.active {{ background:rgba(46,204,113,0.1); color:var(--sidebar-active); border-left-color:var(--sidebar-active); font-weight:600; }}
#sidebar nav a.sub {{ padding-left:44px; font-size:13px; }}

#content {{ margin-left:300px; padding:40px 50px; max-width:900px; width:100%; background:var(--content-bg); min-height:100vh; }}
.section {{ display:none; animation:fadeIn 0.4s; }}
.section.active {{ display:block; }}
@keyframes fadeIn {{ from{{opacity:0;transform:translateY(10px)}} to{{opacity:1;transform:translateY(0)}} }}

h2 {{ color:var(--heading); font-size:28px; margin-bottom:8px; padding-bottom:12px; border-bottom:3px solid var(--accent); }}
h3 {{ color:var(--heading); font-size:20px; margin:28px 0 12px; }}
h4 {{ color:var(--accent2); font-size:16px; margin:20px 0 8px; }}
p {{ margin-bottom:14px; font-size:15px; }}
ul,ol {{ margin:10px 0 16px 24px; }}
li {{ margin-bottom:6px; font-size:15px; }}

.card {{ background:var(--card-bg); border:1px solid var(--border); border-radius:10px; padding:20px; margin:16px 0; }}
.card-title {{ font-weight:700; color:var(--heading); margin-bottom:8px; font-size:16px; }}

.analogy {{ background:linear-gradient(135deg,#e8f5e9,#e3f2fd); border-left:4px solid var(--accent); border-radius:8px; padding:16px 20px; margin:16px 0; }}
.analogy .label {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:var(--accent); font-weight:700; margin-bottom:6px; }}
.warning {{ background:#fff3e0; border-left:4px solid var(--neutral); border-radius:8px; padding:16px 20px; margin:16px 0; }}
.warning .label {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:var(--neutral); font-weight:700; margin-bottom:6px; }}
.info {{ background:#e3f2fd; border-left:4px solid var(--accent2); border-radius:8px; padding:16px 20px; margin:16px 0; }}
.info .label {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:var(--accent2); font-weight:700; margin-bottom:6px; }}

table {{ width:100%; border-collapse:collapse; margin:16px 0; font-size:14px; }}
th {{ background:var(--heading); color:#fff; padding:10px 14px; text-align:left; font-weight:600; }}
td {{ padding:10px 14px; border-bottom:1px solid var(--border); }}
tr:nth-child(even) td {{ background:var(--card-bg); }}

.code {{ background:var(--code-bg); color:var(--code-text); padding:2px 8px; border-radius:4px; font-family:'Consolas','Courier New',monospace; font-size:14px; }}

.img-container {{ margin:20px 0; text-align:center; }}
.img-container img {{ max-width:100%; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.1); }}
.img-caption {{ font-size:13px; color:#777; margin-top:8px; font-style:italic; }}

.flow {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:4px; margin:20px 0; }}
.flow-step {{ background:var(--accent2); color:#fff; padding:8px 16px; border-radius:20px; font-size:13px; font-weight:600; }}
.flow-arrow {{ font-size:20px; color:#999; }}

.badge-pos {{ background:var(--positive); color:#fff; padding:3px 12px; border-radius:12px; font-size:12px; font-weight:600; }}
.badge-neu {{ background:var(--neutral); color:#fff; padding:3px 12px; border-radius:12px; font-size:12px; font-weight:600; }}
.badge-neg {{ background:var(--negative); color:#fff; padding:3px 12px; border-radius:12px; font-size:12px; font-weight:600; }}

#toggle {{ display:none; position:fixed; top:12px; left:12px; z-index:200; background:var(--sidebar-bg); color:#fff; border:none; padding:10px 14px; border-radius:6px; font-size:18px; cursor:pointer; }}
@media (max-width:768px) {{
  #toggle {{ display:block; }}
  #sidebar {{ transform:translateX(-100%); }}
  #sidebar.open {{ transform:translateX(0); }}
  #content {{ margin-left:0; padding:60px 20px 40px; }}
}}
.footer {{ margin-top:40px; padding-top:20px; border-top:1px solid var(--border); color:#999; font-size:13px; text-align:center; }}

/* Navigation buttons */
.nav-buttons {{ display:flex; justify-content:space-between; align-items:center; margin-top:30px; padding-top:20px; border-top:1px solid var(--border); }}
.nav-btn {{ display:inline-flex; align-items:center; gap:8px; padding:10px 24px; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; border:none; transition:all 0.2s; text-decoration:none; }}
.nav-btn.prev {{ background:var(--accent2); color:#fff; }}
.nav-btn.next {{ background:var(--accent); color:#fff; }}
.nav-btn:hover {{ opacity:0.85; transform:translateY(-1px); box-shadow:0 4px 12px rgba(0,0,0,0.15); }}
.nav-btn:disabled {{ background:#ccc; color:#999; cursor:not-allowed; opacity:0.5; transform:none; box-shadow:none; }}
.nav-btn .arrow {{ font-size:18px; }}
.nav-position {{ font-size:13px; color:#999; }}
</style>
</head>
<body>

<button id="toggle" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>

<div id="sidebar">
  <div class="header"><h1>NLP Sentiment Analysis</h1><p>User Guide</p></div>
  <nav id="nav">
    <a href="#" data-section="overview" class="active">📖 Overview</a>
    <a href="#" data-section="what-is-nlp">🧠 What is NLP?</a>
    <a href="#" data-section="what-is-sentiment">😊 What is Sentiment Analysis?</a>
    <a href="#" data-section="why-preprocess">🧹 Why Preprocessing Matters</a>
    <a href="#" data-section="pipeline">🔄 The Complete Pipeline</a>
    <a href="#" data-section="dataset">📂 Section 3-4: Dataset & Exploration</a>
    <a href="#" data-section="preprocessing" class="sub">🔧 Section 5-6: Preprocessing</a>
    <a href="#" data-section="tokens" class="sub">📝 Section 7: Token Visualization</a>
    <a href="#" data-section="stopwords" class="sub">🛑 Section 8: Stop Words</a>
    <a href="#" data-section="lemmatization" class="sub">🌱 Section 9: Lemmatization</a>
    <a href="#" data-section="wordclouds" class="sub">☁️ Section 10: Word Clouds</a>
    <a href="#" data-section="tfidf">📐 Section 11: TF-IDF Features</a>
    <a href="#" data-section="split">✂️ Section 12: Train/Test Split</a>
    <a href="#" data-section="training">🤖 Section 13: Training Models</a>
    <a href="#" data-section="evaluation">📏 Section 14: Evaluation</a>
    <a href="#" data-section="prediction">🔮 Section 15: Predicting Reviews</a>
    <a href="#" data-section="explanation">🔍 Section 16: Explaining Predictions</a>
    <a href="#" data-section="rulebased">⚖️ Section 17: Rule-Based Comparison</a>
    <a href="#" data-section="performance">⏱️ Section 18: Performance</a>
    <a href="#" data-section="saving">💾 Section 19: Saving the Model</a>
    <a href="#" data-section="conclusion">🎯 Conclusion & Next Steps</a>
    <a href="#" data-section="glossary">📚 Glossary</a>
  </nav>
</div>

<div id="content">

<!-- OVERVIEW -->
<div class="section active" id="overview">
  <h2>📖 Overview</h2>
  <p>Welcome to the <strong>NLP Sentiment Analysis</strong> user guide! This guide explains, in plain language, what our sentiment analysis project does and how each part works.</p>
  <div class="analogy"><div class="label">💡 In Simple Terms</div>
    <p>Imagine you have thousands of product reviews and want to know: <strong>Are people happy, unhappy, or neutral?</strong> Instead of reading every review yourself, you teach a computer to read them and classify each one as <span class="badge-pos">Positive</span>, <span class="badge-neu">Neutral</span>, or <span class="badge-neg">Negative</span>.</p>
    <p>That's <strong>sentiment analysis</strong> — and this guide walks you through exactly how it works, step by step.</p>
  </div>
  <h3>What You'll Learn</h3>
  <ul><li>How computers understand human language (NLP)</li><li>How text is cleaned and prepared for analysis</li><li>How machines learn to detect sentiment from reviews</li><li>How we evaluate if the model is any good</li><li>How we can predict sentiment for new, unseen reviews</li></ul>
  <h3>Who This Is For</h3>
  <p>This guide is written for <strong>non-technical readers</strong>. No programming knowledge needed. We use analogies, visuals, and plain English throughout.</p>
  <h3>The Dataset</h3>
  <p>We use ~2,000 product reviews. Each is labeled as one of three sentiments:</p>
  <table><tr><th>Sentiment</th><th>What it means</th><th>Example</th></tr>
    <tr><td><span class="badge-pos">Positive</span></td><td>Happy, satisfied, recommending</td><td>"I love this phone!"</td></tr>
    <tr><td><span class="badge-neu">Neutral</span></td><td>Okay, average, nothing special</td><td>"Average quality."</td></tr>
    <tr><td><span class="badge-neg">Negative</span></td><td>Unhappy, disappointed, complaining</td><td>"Battery is terrible."</td></tr>
  </table>
  <h3>The 20-Step Journey</h3>
  <div class="flow"><span class="flow-step">Load Data</span><span class="flow-arrow">→</span><span class="flow-step">Clean Text</span><span class="flow-arrow">→</span><span class="flow-step">Extract Features</span><span class="flow-arrow">→</span><span class="flow-step">Train Model</span><span class="flow-arrow">→</span><span class="flow-step">Evaluate</span><span class="flow-arrow">→</span><span class="flow-step">Predict</span></div>
  <p>Use the <strong>left sidebar</strong> to jump to any section.</p>
</div>

<!-- WHAT IS NLP -->
<div class="section" id="what-is-nlp">
  <h2>🧠 What is NLP?</h2>
  <p><strong>NLP</strong> (Natural Language Processing) teaches computers to understand human language.</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Think of NLP as a <strong>translator between humans and computers</strong>. Humans speak in words; computers understand numbers. NLP converts "I love this phone!" into something a computer can process.</p></div>
  <h3>What Can NLP Do?</h3>
  <table><tr><th>Task</th><th>Example</th></tr><tr><td>Sentiment Analysis</td><td>Is this review positive or negative?</td></tr><tr><td>Spam Detection</td><td>Is this email spam?</td></tr><tr><td>Translation</td><td>English → French</td></tr><tr><td>Question Answering</td><td>ChatGPT answering questions</td></tr></table>
  <h3>Why Is It Hard?</h3>
  <ul><li><strong>Sarcasm</strong> — "Oh great, another broken phone"</li><li><strong>Negations</strong> — "not good" ≠ "good"</li><li><strong>Context</strong> — "sick" can mean "awesome" or "ill"</li><li><strong>Noise</strong> — URLs, emojis, typos, ALL CAPS</li></ul>
</div>

<!-- WHAT IS SENTIMENT -->
<div class="section" id="what-is-sentiment">
  <h2>😊 What is Sentiment Analysis?</h2>
  <p>Determining the emotional tone behind text — <span class="badge-pos">Positive</span>, <span class="badge-neu">Neutral</span>, or <span class="badge-neg">Negative</span>?</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>A friend reads a movie review and says "This person liked the movie." That's sentiment analysis by a human. We teach a computer to do it at scale — thousands of reviews in seconds.</p></div>
  <h3>Real-World Applications</h3>
  <table><tr><th>Industry</th><th>How It's Used</th></tr><tr><td>📱 E-commerce</td><td>Amazon analyzing product reviews</td></tr><tr><td>🎬 Entertainment</td><td>Rotten Tomatoes scoring</td></tr><tr><td>🐦 Social Media</td><td>Brand monitoring on Twitter</td></tr><tr><td>🏦 Banking</td><td>Customer feedback analysis</td></tr></table>
  <h3>Two Approaches</h3>
  <div class="card"><div class="card-title">1. Rule-Based (Dictionary Lookup)</div><p>Pre-built dictionary: "good"=+0.7, "bad"=-0.7. No learning. Examples: TextBlob, VADER.</p></div>
  <div class="card"><div class="card-title">2. Machine Learning (Learned from Data)</div><p>Computer reads labeled examples and learns patterns. Examples: Logistic Regression, Naive Bayes, SVM.</p></div>
</div>

<!-- WHY PREPROCESS -->
<div class="section" id="why-preprocess">
  <h2>🧹 Why Preprocessing Matters</h2>
  <p>Raw text is messy — URLs, emojis, HTML, punctuation, inconsistent capitalization.</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Like sorting mail: some envelopes are torn, stained, in foreign languages. Before sorting into "bills" and "personal letters", you clean them up. That's what preprocessing does for text.</p></div>
  <h3>Our 10-Step Cleaning Pipeline</h3>
  <div class="flow"><span class="flow-step">Lowercase</span><span class="flow-arrow">→</span><span class="flow-step">Remove URLs</span><span class="flow-arrow">→</span><span class="flow-step">Remove HTML</span><span class="flow-arrow">→</span><span class="flow-step">Remove Emojis</span><span class="flow-arrow">→</span><span class="flow-step">Remove Numbers</span></div>
  <div class="flow"><span class="flow-step">Remove Punctuation</span><span class="flow-arrow">→</span><span class="flow-step">Tokenize</span><span class="flow-arrow">→</span><span class="flow-step">Remove Stop Words</span><span class="flow-arrow">→</span><span class="flow-step">Lemmatize</span></div>
  <div class="warning"><div class="label">⚠️ Critical</div><p>We <strong>keep negation words</strong> (not, no, never) because "not good" ≠ "good". Removing "not" would destroy sentiment information!</p></div>
</div>

<!-- PIPELINE -->
<div class="section" id="pipeline">
  <h2>🔄 The Complete Pipeline</h2>
  <div class="flow"><span class="flow-step">Raw Review</span><span class="flow-arrow">→</span><span class="flow-step">Preprocess</span><span class="flow-arrow">→</span><span class="flow-step">TF-IDF Vector</span><span class="flow-arrow">→</span><span class="flow-step">Model</span><span class="flow-arrow">→</span><span class="flow-step">Sentiment</span></div>
  <h3>Step-by-Step Example</h3>
  <div class="card"><div class="card-title">Input: "I REALLY Loved this Phone!!! 😊 Visit https://abc.com"</div>
    <table><tr><th>Step</th><th>What Happens</th><th>Result</th></tr>
      <tr><td>1. Lowercase</td><td>All letters lowercase</td><td>"i really loved this phone!!! 😊 visit https://abc.com"</td></tr>
      <tr><td>2. Remove URLs</td><td>Delete web links</td><td>"...phone!!! 😊 visit"</td></tr>
      <tr><td>3. Remove Emojis</td><td>Delete emojis</td><td>"...phone!!! visit"</td></tr>
      <tr><td>4. Remove Punctuation</td><td>Delete !!!</td><td>"i really loved this phone visit"</td></tr>
      <tr><td>5. Tokenize</td><td>Split into words</td><td>['i','really','loved','this','phone','visit']</td></tr>
      <tr><td>6. Remove Stop Words</td><td>Delete "i","this"</td><td>['really','loved','phone','visit']</td></tr>
      <tr><td>7. Lemmatize</td><td>"loved"→"love"</td><td>['really','love','phone','visit']</td></tr>
      <tr><td>8. Model Predicts</td><td>Computer decides</td><td><span class="badge-pos">Positive</span></td></tr>
    </table>
  </div>
</div>

<!-- DATASET -->
<div class="section" id="dataset">
  <h2>📂 Section 3-4: Dataset & Exploration</h2>
  <p>We load ~2,000 product reviews and explore them.</p>
  <h3>What We Check</h3>
  <table><tr><th>Check</th><th>Why</th></tr><tr><td>First 10 rows</td><td>See what data looks like</td></tr><tr><td>Shape</td><td>How much data?</td></tr><tr><td>Missing values</td><td>Any gaps?</td></tr><tr><td>Class distribution</td><td>Is data balanced?</td></tr></table>
  <h3>Sentiment Distribution</h3>
  <div class="img-container"><img src="{images.get('sentiment_distribution','')}" alt="Sentiment Distribution"><div class="img-caption">Figure 1: Bar chart (left) and pie chart (right) showing balanced distribution — ~667 reviews per class.</div></div>
  <div class="info"><div class="label">📊 Why Balance Matters</div><p>If 90% were Positive, the model could just guess "Positive" every time. Balanced data forces real learning.</p></div>
</div>

<!-- PREPROCESSING -->
<div class="section" id="preprocessing">
  <h2>🔧 Section 5-6: Preprocessing Pipeline</h2>
  <p>The heart of NLP — 10 cleaning steps, each doing one specific job.</p>
  <table><tr><th>#</th><th>Function</th><th>What It Does</th><th>Example</th></tr>
    <tr><td>1</td><td>Lowercase</td><td>All letters lowercase</td><td>"GREAT"→"great"</td></tr>
    <tr><td>2</td><td>Remove URLs</td><td>Delete web links</td><td>"Visit https://..."→"Visit"</td></tr>
    <tr><td>3</td><td>Remove HTML</td><td>Delete HTML tags</td><td>"&lt;br&gt;Hello"→"Hello"</td></tr>
    <tr><td>4</td><td>Remove Emojis</td><td>Delete emojis</td><td>"Great 😊"→"Great"</td></tr>
    <tr><td>5</td><td>Remove Numbers</td><td>Delete numbers</td><td>"50% off"→"off"</td></tr>
    <tr><td>6</td><td>Remove Punctuation</td><td>Delete !,.?</td><td>"Great!!!"→"Great"</td></tr>
    <tr><td>7</td><td>Tokenize</td><td>Split into words</td><td>"love phone"→['love','phone']</td></tr>
    <tr><td>8</td><td>Remove Stop Words</td><td>Delete common words</td><td>['the','love']→['love']</td></tr>
    <tr><td>9</td><td>Lemmatize</td><td>Base form</td><td>"loved"→"love"</td></tr>
    <tr><td>10</td><td>Remove Extra Spaces</td><td>Clean whitespace</td><td>"  love  "→"love"</td></tr>
  </table>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Like washing laundry: separate colors (lowercase), remove stains (URLs), remove tags (HTML), fold (tokenize), discard unneeded items (stop words), organize by type (lemmatize).</p></div>
</div>

<!-- TOKENS -->
<div class="section" id="tokens">
  <h2>📝 Section 7: Token Visualization</h2>
  <p>We compare text <strong>before</strong> and <strong>after</strong> preprocessing.</p>
  <ul><li><strong>Original tokens</strong> — all words including noise</li><li><strong>Processed tokens</strong> — clean, meaningful words</li><li><strong>Word count reduction</strong> — typically ~50% reduction</li></ul>
  <p>We also show the <strong>top 20 most frequent words</strong> across all reviews in a bar chart.</p>
</div>

<!-- STOP WORDS -->
<div class="section" id="stopwords">
  <h2>🛑 Section 8: Stop Word Visualization</h2>
  <p><strong>Stop words</strong> are extremely common words: <em>the, is, at, which, on, this, a...</em></p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Like reading a book where every page says "the and is of to a" — these words are everywhere but tell you nothing about the story. Removing them lets you focus on actual content.</p></div>
  <div class="warning"><div class="label">⚠️ We Keep Negations!</div><p>"not", "no", "never" are kept because they <strong>flip sentiment</strong>: "good"→Positive, "not good"→Negative. Removing "not" would make them identical!</p></div>
</div>

<!-- LEMMATIZATION -->
<div class="section" id="lemmatization">
  <h2>🌱 Section 9: Lemmatization Demo</h2>
  <p>Converts words to their base dictionary form (lemma).</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>"Running", "runs", "ran" all come from the root <strong>"run"</strong>. Lemmatization groups them so the model treats them as one concept.</p></div>
  <table><tr><th>Word</th><th>Lemma</th><th>Why</th></tr><tr><td>running</td><td>run</td><td>Verb→base</td></tr><tr><td>cars</td><td>car</td><td>Plural→singular</td></tr><tr><td>loved</td><td>love</td><td>Past→base</td></tr><tr><td>better</td><td>well</td><td>Comparative→base (smart!)</td></tr><tr><td>mice</td><td>mouse</td><td>Irregular plural</td></tr><tr><td>went</td><td>go</td><td>Irregular past</td></tr></table>
  <p>We use <strong>spaCy</strong> because it's POS-aware — it knows grammar, so it handles irregular forms that simpler methods can't.</p>
</div>

<!-- WORD CLOUDS -->
<div class="section" id="wordclouds">
  <h2>☁️ Section 10: Word Clouds</h2>
  <p>Visual summaries where <strong>bigger words appear more frequently</strong>.</p>
  <h3>Positive Reviews</h3>
  <div class="img-container"><img src="{images.get('wordcloud_positive','')}" alt="Positive Word Cloud"><div class="img-caption">Figure 2: Positive reviews — "love", "great", "amazing", "fantastic" dominate.</div></div>
  <h3>Negative Reviews</h3>
  <div class="img-container"><img src="{images.get('wordcloud_negative','')}" alt="Negative Word Cloud"><div class="img-caption">Figure 3: Negative reviews — "terrible", "worst", "awful", "waste" dominate.</div></div>
  <h3>Neutral Reviews</h3>
  <div class="img-container"><img src="{images.get('wordcloud_neutral','')}" alt="Neutral Word Cloud"><div class="img-caption">Figure 4: Neutral reviews — "average", "okay", "standard", "decent" dominate.</div></div>
  <div class="info"><div class="label">🔍 What This Tells Us</div><p>Each class has distinctly different vocabulary — exactly what the model uses to classify new reviews.</p></div>
</div>

<!-- TF-IDF -->
<div class="section" id="tfidf">
  <h2>📐 Section 11: TF-IDF Feature Extraction</h2>
  <p>Computers understand <strong>numbers</strong>, not words. TF-IDF converts text into numerical vectors.</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>At a party: someone says "the" — you barely notice (too common). Someone says "elephant" — you pay attention (rare and specific). TF-IDF gives <strong>high weight to rare, distinctive words</strong> and <strong>low weight to common ones</strong>.</p></div>
  <table><tr><th>Component</th><th>What It Measures</th></tr><tr><td>TF (Term Frequency)</td><td>How often a word appears in this review</td></tr><tr><td>IDF (Inverse Doc Frequency)</td><td>How rare the word is across all reviews</td></tr><tr><td>TF-IDF</td><td>TF × IDF — the final score</td></tr></table>
</div>

<!-- SPLIT -->
<div class="section" id="split">
  <h2>✂️ Section 12: Train/Test Split</h2>
  <table><tr><th>Set</th><th>Size</th><th>Purpose</th></tr><tr><td>Training set</td><td>80% (1,600 reviews)</td><td>Model learns from these</td></tr><tr><td>Test set</td><td>20% (400 reviews)</td><td>Test on unseen data</td></tr></table>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Like a <strong>student taking an exam</strong>. Training set = textbook to study. Test set = final exam with <strong>never-before-seen questions</strong>. If the student only memorized without understanding, they'll fail.</p></div>
</div>

<!-- TRAINING -->
<div class="section" id="training">
  <h2>🤖 Section 13: Training Models</h2>
  <p>We train <strong>three different models</strong> and compare them.</p>
  <div class="card"><div class="card-title">1. Logistic Regression</div><p>Learns a weight for each word. Multiplies word weights by TF-IDF scores, adds up, predicts based on total. <strong>Fast, interpretable.</strong></p></div>
  <div class="card"><div class="card-title">2. Naive Bayes</div><p>Uses probability: "Given these words, what's the probability this is Positive?" Picks highest. <strong>Great for text.</strong></p></div>
  <div class="card"><div class="card-title">3. Linear SVM</div><p>Finds the best boundary line separating classes. Maximizes the gap between them. <strong>Often highest accuracy.</strong></p></div>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Three students studying for the same exam: one assigns importance weights to topics (LR), one calculates probabilities (NB), one draws boundaries between right/wrong (SVM). We compare their exam scores.</p></div>
</div>

<!-- EVALUATION -->
<div class="section" id="evaluation">
  <h2>📏 Section 14: Model Evaluation</h2>
  <table><tr><th>Metric</th><th>What It Means</th></tr><tr><td>Accuracy</td><td>Overall % of correct predictions</td></tr><tr><td>Precision</td><td>Of predicted positives, how many were actually positive?</td></tr><tr><td>Recall</td><td>Of actual positives, how many did we find?</td></tr><tr><td>F1 Score</td><td>Balanced score combining precision and recall</td></tr></table>
  <h3>Confusion Matrix</h3>
  <div class="img-container"><img src="{images.get('confusion_matrix','')}" alt="Confusion Matrix"><div class="img-caption">Figure 5: Diagonal = correct predictions. Off-diagonal = mistakes.</div></div>
  <div class="info"><div class="label">📊 How to Read</div><ul><li><strong>Diagonal</strong> = correct (good!)</li><li><strong>Off-diagonal</strong> = mistakes</li><li><strong>Darker blue</strong> = higher count</li></ul></div>
</div>

<!-- PREDICTION -->
<div class="section" id="prediction">
  <h2>🔮 Section 15: Predicting New Reviews</h2>
  <div class="flow"><span class="flow-step">Type Review</span><span class="flow-arrow">→</span><span class="flow-step">Preprocess</span><span class="flow-arrow">→</span><span class="flow-step">TF-IDF</span><span class="flow-arrow">→</span><span class="flow-step">Model</span><span class="flow-arrow">→</span><span class="flow-step">Result</span></div>
  <table><tr><th>Output</th><th>Example</th></tr><tr><td>Processed review</td><td>"fantastic phone"</td></tr><tr><td>Predicted sentiment</td><td><span class="badge-pos">Positive</span></td></tr><tr><td>Confidence</td><td>92%</td></tr><tr><td>Probabilities</td><td>Pos:92%, Neu:5%, Neg:3%</td></tr></table>
  <div class="info"><div class="label">🚀 FastAPI Ready</div><p>This function becomes the backend endpoint when you build a web app.</p></div>
</div>

<!-- EXPLANATION -->
<div class="section" id="explanation">
  <h2>🔍 Section 16: Explaining Predictions</h2>
  <p>We show <strong>why</strong> the model made each prediction using Logistic Regression coefficients.</p>
  <div class="analogy"><div class="label">💡 Analogy</div><p>A judge who says "Guilty" but won't explain = black box. A judge who says "Guilty because evidence A, B, C" = what we do here. We show which words "voted" for each sentiment.</p></div>
</div>

<!-- RULE BASED -->
<div class="section" id="rulebased">
  <h2>⚖️ Section 17: Rule-Based Comparison</h2>
  <div class="card"><div class="card-title">TextBlob</div><p>Dictionary lookup: "good"=+0.7, "bad"=-0.7. Simple, naive, doesn't handle negations well.</p></div>
  <div class="card"><div class="card-title">VADER</div><p>Smarter dictionary — handles negations, punctuation ("good!!!"), capitalization ("GREAT"), slang.</p></div>
  <table><tr><th></th><th>Rule-Based</th><th>ML Model</th></tr><tr><td>Training</td><td>None (fixed dictionary)</td><td>Learns from 1,600 reviews</td></tr><tr><td>Adapts?</td><td>No</td><td>Yes</td></tr><tr><td>Accuracy</td><td>~50-60%</td><td>~70-80%+</td></tr></table>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Rule-based = tourist with fixed phrasebook. ML model = local who's lived there for years and knows the nuances.</p></div>
</div>

<!-- PERFORMANCE -->
<div class="section" id="performance">
  <h2>⏱️ Section 18: Performance Metrics</h2>
  <table><tr><th>Stage</th><th>Typical Time</th></tr><tr><td>Preprocessing 2,000 reviews</td><td>~10-20s</td></tr><tr><td>TF-IDF transform</td><td>~1-2s</td></tr><tr><td>Train models</td><td>~0.1-3s</td></tr><tr><td>Predict 400 reviews</td><td>~0.01s</td></tr></table>
  <div class="info"><div class="label">⚡ Key Takeaway</div><p>Entire pipeline runs in under 30 seconds — practical for real-world use.</p></div>
</div>

<!-- SAVING -->
<div class="section" id="saving">
  <h2>💾 Section 19: Saving the Model</h2>
  <table><tr><th>File</th><th>Contains</th><th>Size</th></tr><tr><td>sentiment_model.pkl</td><td>Trained model</td><td>~20 KB</td></tr><tr><td>tfidf_vectorizer.pkl</td><td>TF-IDF vectorizer</td><td>~9 KB</td></tr></table>
  <div class="analogy"><div class="label">💡 Analogy</div><p>Like <strong>saving a video game</strong>. You don't replay from Level 1 every time. The save file stores your progress. Loading it puts you instantly back where you left off.</p></div>
  <div class="info"><div class="label">🚀 Web App Ready</div><p>These 2 files + preprocessing.py = everything needed for a FastAPI web app backend.</p></div>
</div>

<!-- CONCLUSION -->
<div class="section" id="conclusion">
  <h2>🎯 Conclusion & Next Steps</h2>
  <h3>What We Built</h3>
  <ol><li>Load and explore 2,000 reviews</li><li>Clean text through 10-step pipeline</li><li>Convert to numbers via TF-IDF</li><li>Train 3 models, pick the best</li><li>Evaluate with multiple metrics</li><li>Predict new reviews with confidence</li><li>Explain why predictions were made</li><li>Compare ML vs rule-based</li><li>Save model for future use</li></ol>
  <h3>Key Takeaways</h3>
  <div class="card"><ul>
    <li><strong>Preprocessing matters</strong> — cleaning noise improves quality</li>
    <li><strong>Negations must be kept</strong> — "not good" ≠ "good"</li>
    <li><strong>Lemmatization &gt; stemming</strong> — handles irregular forms</li>
    <li><strong>TF-IDF is powerful</strong> — weights by distinctiveness</li>
    <li><strong>ML &gt; rule-based</strong> — learns domain-specific patterns</li>
  </ul></div>
  <h3>Next Steps</h3>
  <ol><li>Build a FastAPI backend</li><li>Add a web UI (Streamlit/React)</li><li>Try larger datasets (IMDb 50K)</li><li>Experiment with n-grams</li><li>Try deep learning (BERT)</li></ol>
</div>

<!-- GLOSSARY -->
<div class="section" id="glossary">
  <h2>📚 Glossary</h2>
  <p>Every technical term used in this guide, with its full expansion, plain-English explanation, and a real-world example.</p>
  <table><tr><th>Abbreviation</th><th>Full Form</th><th>What It Means</th><th>Example</th></tr>
    <tr><td><strong>NLP</strong></td><td>Natural Language Processing</td><td>Teaching computers to understand, interpret, and work with human language — bridging the gap between words and numbers.</td><td>A computer reading "I love this phone!" and understanding it's a positive statement.</td></tr>
    <tr><td><strong>Sentiment Analysis</strong></td><td>Sentiment Analysis (Opinion Mining)</td><td>Determining the emotional tone behind a piece of text — classifying it as positive, negative, or neutral.</td><td>Amazon scanning 10,000 reviews and labeling each as "happy" or "unhappy" automatically.</td></tr>
    <tr><td><strong>Preprocessing</strong></td><td>Text Preprocessing</td><td>Cleaning and normalizing raw text before feeding it to a model — removing noise like URLs, emojis, and punctuation.</td><td>Converting "GREAT phone!!! 😊 Visit https://x.com" into "great phone" — clean and simple.</td></tr>
    <tr><td><strong>Tokenization</strong></td><td>Tokenization</td><td>Splitting a sentence into individual words (tokens) so the computer can process each word separately.</td><td>"I love phones" → ['I', 'love', 'phones'] — three separate tokens.</td></tr>
    <tr><td><strong>Stop Words</strong></td><td>Stop Words</td><td>Extremely common words that appear in almost every sentence and carry little meaning — removed to focus on important words.</td><td>"the", "is", "at", "which", "on" — removed; but "not" is kept because it flips sentiment.</td></tr>
    <tr><td><strong>Lemmatization</strong></td><td>Lemmatization</td><td>Converting a word to its base dictionary form (lemma) so variants are treated as the same word.</td><td>"loved" → "love", "running" → "run", "better" → "well", "mice" → "mouse".</td></tr>
    <tr><td><strong>Stemming</strong></td><td>Stemming</td><td>A cruder version of lemmatization that chops word endings without understanding grammar — faster but less accurate.</td><td>"running" → "run" (works), but "better" → "better" (fails — can't handle irregulars).</td></tr>
    <tr><td><strong>TF</strong></td><td>Term Frequency</td><td>How often a word appears in a single review. Frequent words get higher scores.</td><td>If "love" appears 3 times in a review, its TF is high for that review.</td></tr>
    <tr><td><strong>IDF</strong></td><td>Inverse Document Frequency</td><td>How rare a word is across all reviews. Words in every review get low scores; unique words get high scores.</td><td>"the" is in every review → low IDF. "fantastic" is rare → high IDF.</td></tr>
    <tr><td><strong>TF-IDF</strong></td><td>Term Frequency–Inverse Document Frequency</td><td>TF × IDF. Gives high weight to words that are frequent in a review but rare across all reviews — capturing distinctiveness.</td><td>"love" in a review (high TF) that few other reviews contain (high IDF) → high TF-IDF score.</td></tr>
    <tr><td><strong>Feature Extraction</strong></td><td>Feature Extraction</td><td>Converting text into numerical vectors that a machine learning model can process — turning words into numbers.</td><td>The word "love" might become the number 0.8, "hate" might become -0.9.</td></tr>
    <tr><td><strong>Train/Test Split</strong></td><td>Train/Test Split</td><td>Dividing data into two parts: the model learns from the training set and is tested on the unseen test set.</td><td>1,600 reviews for training, 400 for testing — like studying a textbook then taking an exam.</td></tr>
    <tr><td><strong>Logistic Regression</strong></td><td>Logistic Regression</td><td>A model that learns a weight (number) for each word, then adds up the weights to decide the sentiment.</td><td>"love" = +1.5, "terrible" = -2.0. Review with "love" → total is positive → predicted Positive.</td></tr>
    <tr><td><strong>Naive Bayes</strong></td><td>Naive Bayes Classifier</td><td>A model using probability theory: "Given these words, what's the probability this review is Positive?" Picks the most likely class.</td><td>Sees "love" and "amazing" → calculates 85% chance Positive → predicts Positive.</td></tr>
    <tr><td><strong>SVM</strong></td><td>Support Vector Machine</td><td>A model that finds the best boundary line (or hyperplane) separating Positive from Negative from Neutral reviews, maximizing the gap.</td><td>Draws a line between "love" cluster and "hate" cluster — new reviews fall on one side or the other.</td></tr>
    <tr><td><strong>CalibratedClassifierCV</strong></td><td>Calibrated Classifier Cross-Validation</td><td>A wrapper that enables SVM to output probability scores (not just predictions) by calibrating its outputs.</td><td>SVM says "Positive" → calibration adds "with 87% confidence" instead of just a bare label.</td></tr>
    <tr><td><strong>Accuracy</strong></td><td>Accuracy</td><td>The percentage of all predictions that were correct — the simplest metric.</td><td>If 360 out of 400 test reviews were correctly classified, accuracy = 90%.</td></tr>
    <tr><td><strong>Precision</strong></td><td>Precision</td><td>Of all reviews the model predicted as Positive, what fraction were actually Positive? Measures "false alarm" rate.</td><td>Model says 100 are Positive, 90 actually are → precision = 90%. 10 were false alarms.</td></tr>
    <tr><td><strong>Recall</strong></td><td>Recall (Sensitivity)</td><td>Of all reviews that are actually Positive, how many did the model find? Measures "missed" rate.</td><td>120 reviews are truly Positive, model found 96 → recall = 80%. It missed 24.</td></tr>
    <tr><td><strong>F1 Score</strong></td><td>F1 Score (F-measure)</td><td>The harmonic mean of Precision and Recall — a balanced score that punishes extreme tradeoffs.</td><td>Precision=90%, Recall=80% → F1=84%. If either is very low, F1 drops significantly.</td></tr>
    <tr><td><strong>Confusion Matrix</strong></td><td>Confusion Matrix</td><td>A table showing exactly where the model got confused — which classes were mistaken for which.</td><td>Diagonal = correct predictions. Off-diagonal: 5 Negative reviews were misclassified as Neutral.</td></tr>
    <tr><td><strong>ROC Curve</strong></td><td>Receiver Operating Characteristic Curve</td><td>A graph showing the tradeoff between catching positives and avoiding false alarms. Only works for 2-class problems.</td><td>Used in binary (Positive vs Negative). Our 3-class project uses per-class bar charts instead.</td></tr>
    <tr><td><strong>Rule-Based</strong></td><td>Rule-Based (Lexicon-Based)</td><td>Using a fixed dictionary of word scores — no learning, no training. "good"=+0.7, "bad"=-0.7, just look it up.</td><td>TextBlob: looks up "good" → +0.7, "bad" → -0.7, adds them up. Same dictionary forever.</td></tr>
    <tr><td><strong>Machine Learning</strong></td><td>Machine Learning (ML)</td><td>Learning patterns from labeled data instead of using fixed rules. The model improves as it sees more examples.</td><td>Show 1,600 labeled reviews → model learns "battery"+"awful" = negative. No human coded that rule.</td></tr>
    <tr><td><strong>TextBlob</strong></td><td>TextBlob</td><td>A Python library that does sentiment analysis using a pre-built word dictionary. Simple, fast, but naive — doesn't handle negations well.</td><td>"not good" might still score positive because TextBlob sees "good"=+0.7 and ignores "not".</td></tr>
    <tr><td><strong>VADER</strong></td><td>Valence Aware Dictionary for sEntiment Reasoning</td><td>A smarter rule-based tool designed for social media — handles negations, punctuation ("good!!!"), capitalization ("GREAT"), and slang.</td><td>"not good" → VADER flips the score to negative. "GREAT!!!" → amplifies the positive score.</td></tr>
    <tr><td><strong>spaCy</strong></td><td>spaCy</td><td>An industrial-strength NLP library used for lemmatization. It's POS-aware — knows grammar, so it handles irregular forms correctly.</td><td>spaCy knows "better" is a comparative of "good" → lemma = "well". Stemming can't do this.</td></tr>
    <tr><td><strong>NLTK</strong></td><td>Natural Language Toolkit</td><td>A Python NLP library providing tokenization, stop word lists, and lexical resources like WordNet.</td><td>NLTK splits "I love phones" into ['I', 'love', 'phones'] and provides the English stop word list.</td></tr>
    <tr><td><strong>POS</strong></td><td>Part of Speech</td><td>The grammatical role of a word in a sentence — noun, verb, adjective, adverb, etc. Used by spaCy for accurate lemmatization.</td><td>"run" as a verb → lemma "run". "run" as a noun (a run in stockings) → lemma "run". Context matters.</td></tr>
    <tr><td><strong>WordNet</strong></td><td>WordNet</td><td>A large lexical database of English where words are grouped into sets of synonyms (synsets) with semantic relations.</td><td>WordNet links "happy" and "joyful" as related concepts, helping with lemmatization.</td></tr>
    <tr><td><strong>N-gram</strong></td><td>N-gram</td><td>A sequence of N consecutive words. Unigrams = 1 word, bigrams = 2 words. Captures word combinations like "not good".</td><td>Unigram: "not", "good" (separate). Bigram: "not good" (together — captures the negation pattern).</td></tr>
    <tr><td><strong>Corpus</strong></td><td>Corpus</td><td>A collection of texts used for analysis. Our corpus is 2,000 product reviews.</td><td>All 2,000 reviews together form the corpus. TF-IDF calculates rarity across this entire corpus.</td></tr>
    <tr><td><strong>Vocabulary</strong></td><td>Vocabulary</td><td>The set of all unique words the model knows after processing the corpus. Each word becomes a feature.</td><td>2,000 reviews might contain 3,500 unique words → vocabulary size = 3,500 features.</td></tr>
    <tr><td><strong>Vector</strong></td><td>Vector (Feature Vector)</td><td>A list of numbers representing a review — one number per word in the vocabulary. This is what the model actually processes.</td><td>Review "love phone" → [0, 0.8, 0, 0.5, 0, ...] — mostly zeros with scores for "love" and "phone".</td></tr>
    <tr><td><strong>Model Fitting</strong></td><td>Model Fitting (Training)</td><td>The process where the model learns from training data — adjusting its internal weights to minimize prediction errors.</td><td>model.fit(X_train, y_train) → the model studies 1,600 labeled reviews and adjusts its weights.</td></tr>
    <tr><td><strong>Inference</strong></td><td>Inference (Prediction)</td><td>Using a trained model to predict the sentiment of new, unseen reviews.</td><td>model.predict(new_review) → "Positive" with 92% confidence. The model is now doing inference.</td></tr>
    <tr><td><strong>Overfitting</strong></td><td>Overfitting</td><td>When a model memorizes the training data instead of learning general patterns — it fails on new data.</td><td>Model gets 99% on training data but only 60% on test data → it overfit (memorized, didn't generalize).</td></tr>
    <tr><td><strong>Stratification</strong></td><td>Stratification</td><td>Ensuring the train and test sets have the same proportion of each class — prevents imbalance.</td><td>If data is 33% Positive, 33% Neutral, 33% Negative → both train and test sets maintain this 1:1:1 ratio.</td></tr>
    <tr><td><strong>spaCy Model</strong></td><td>en_core_web_sm</td><td>A small English language model for spaCy — contains vocabulary, syntax, and POS tags needed for lemmatization.</td><td>Loaded once at startup: spacy.load("en_core_web_sm") → ready to lemmatize any English text.</td></tr>
    <tr><td><strong>FastAPI</strong></td><td>FastAPI</td><td>A modern Python web framework for building APIs quickly. Our saved model can be served as a web API using FastAPI.</td><td>A web app sends a review to our FastAPI endpoint → gets back sentiment: Positive, confidence: 0.92.</td></tr>
    <tr><td><strong>.pkl file</strong></td><td>Pickle file (Python serialized object)</td><td>A saved model file — like a save game. Contains the trained weights so you can reuse the model without retraining.</td><td>sentiment_model.pkl (20 KB) → load it, predict immediately. No need to retrain from scratch.</td></tr>
    <tr><td><strong>joblib</strong></td><td>joblib</td><td>A Python library for saving and loading large objects (like trained models) efficiently — faster than standard pickle.</td><td>joblib.dump(model, "model.pkl") saves. joblib.load("model.pkl") restores. Simple as save/load.</td></tr>
    <tr><td><strong>BERT</strong></td><td>Bidirectional Encoder Representations from Transformers</td><td>A state-of-the-art deep learning model for NLP — understands context bidirectionally. Mentioned as a future upgrade.</td><td>BERT understands "not bad" means "good" by reading the full sentence in both directions — beyond our TF-IDF approach.</td></tr>
  </table>
  <div class="footer"><p>NLP Sentiment Analysis Demo — User Guide | Generated from SentimentAnalysis.ipynb</p></div>
</div>

<!-- Navigation buttons (outside all sections, always visible) -->
<div class="nav-buttons">
  <button class="nav-btn prev" id="prevBtn" onclick="navigate(-1)"><span class="arrow">←</span> Previous</button>
  <span class="nav-position" id="navPosition">1 / 22</span>
  <button class="nav-btn next" id="nextBtn" onclick="navigate(1)">Next <span class="arrow">→</span></button>
</div>

</div>

<script>
const links = document.querySelectorAll('#nav a');
const sections = document.querySelectorAll('.section');
let currentIndex = 0;

function showSection(index) {{
  if (index < 0 || index >= links.length) return;
  currentIndex = index;
  const target = links[index].dataset.section;
  links.forEach(l => l.classList.remove('active'));
  links[index].classList.add('active');
  sections.forEach(s => s.id === target ? s.classList.add('active') : s.classList.remove('active'));
  document.getElementById('sidebar').classList.remove('open');
  window.scrollTo(0, 0);
  // Update nav buttons
  document.getElementById('prevBtn').disabled = (index === 0);
  document.getElementById('nextBtn').disabled = (index === links.length - 1);
  document.getElementById('navPosition').textContent = (index + 1) + ' / ' + links.length;
}}

function navigate(direction) {{
  showSection(currentIndex + direction);
}}

links.forEach((link, i) => {{
  link.addEventListener('click', (e) => {{
    e.preventDefault();
    showSection(i);
  }});
}});

// Keyboard navigation
document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowLeft') navigate(-1);
  if (e.key === 'ArrowRight') navigate(1);
}});

// Initialize
showSection(0);
</script>
</body>
</html>'''

with open(HTML_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n✅ Generated: {HTML_FILE} ({os.path.getsize(HTML_FILE)/1024:.0f} KB)")
print(f"   Self-contained with {len(images)} embedded images")
print(f"   Open in any browser — shareable as a single file!")