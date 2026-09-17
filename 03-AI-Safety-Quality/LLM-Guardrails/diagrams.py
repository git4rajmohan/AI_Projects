# Graphviz DOT strings for each experiment's message flow diagram.
# Rendered via st.graphviz_chart() in Streamlit.

_COMMON = """
  node [shape=box style=filled fontname="Arial" fontsize=12]
  edge [fontname="Arial" fontsize=10]
"""

_USER = 'User [label="User\\nMessage" shape=oval fillcolor="#D6EAF8"]'
_BOT  = 'Bot  [label="Bot\\nResponse"  shape=oval fillcolor="#D6EAF8"]'

DIAGRAMS = {

    1: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  LLM [label="Raw LLM\\n(No Guardrails)" fillcolor="#FADBD8"]
  {_BOT}

  User -> LLM [label=" no filtering "]
  LLM  -> Bot
}}""",

    2: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  Intent [label="Intent Check\\n(LLM Call 1)" fillcolor="#FEF9E7"]
  Block  [label="Refuse:\\nOff-Topic" fillcolor="#FADBD8"]
  LLM    [label="LLM Answer\\n(LLM Call 2)" fillcolor="#D5F5E3"]
  {_BOT}

  User   -> Intent
  Intent -> Block [label="off-topic"]
  Intent -> LLM   [label="on-topic"]
  Block  -> Bot
  LLM    -> Bot
}}""",

    3: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  Intent  [label="Intent Check\\n(LLM Call 1)" fillcolor="#FEF9E7"]
  BkOT    [label="Refuse:\\nOff-Topic"   fillcolor="#FADBD8"]
  BkJB    [label="Refuse:\\nJailbreak"   fillcolor="#FADBD8"]
  LLM     [label="LLM Answer\\n(LLM Call 2)" fillcolor="#D5F5E3"]
  {_BOT}

  User   -> Intent
  Intent -> BkOT [label="off-topic"]
  Intent -> BkJB [label="jailbreak"]
  Intent -> LLM  [label="on-topic"]
  BkOT   -> Bot
  BkJB   -> Bot
  LLM    -> Bot
}}""",

    4: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  Intent [label="Intent Check\\n(LLM Call 1)"  fillcolor="#FEF9E7"]
  BkOT   [label="Refuse:\\nOff-Topic"          fillcolor="#FADBD8"]
  BkJB   [label="Refuse:\\nJailbreak"          fillcolor="#FADBD8"]
  BkST   [label="Refuse:\\nSensitive Topic"    fillcolor="#FADBD8"]
  LLM    [label="LLM Answer\\n(LLM Call 2)"   fillcolor="#D5F5E3"]
  {_BOT}

  User   -> Intent
  Intent -> BkOT [label="off-topic"]
  Intent -> BkJB [label="jailbreak"]
  Intent -> BkST [label="sensitive"]
  Intent -> LLM  [label="allowed"]
  BkOT   -> Bot
  BkJB   -> Bot
  BkST   -> Bot
  LLM    -> Bot
}}""",

    5: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  Intent  [label="Intent Check\\n(LLM Call 1)"     fillcolor="#FEF9E7"]
  BkOT    [label="Refuse:\\nOff-Topic"             fillcolor="#FADBD8"]
  BkJB    [label="Refuse:\\nJailbreak"             fillcolor="#FADBD8"]
  BkST    [label="Refuse:\\nSensitive Topic"       fillcolor="#FADBD8"]
  Dialog  [label="Scripted Dialog\\ngreeting / help / bye" fillcolor="#E8DAEF"]
  LLM     [label="LLM Answer\\n(LLM Call 2)"      fillcolor="#D5F5E3"]
  {_BOT}

  User   -> Intent
  Intent -> BkOT   [label="off-topic"]
  Intent -> BkJB   [label="jailbreak"]
  Intent -> BkST   [label="sensitive"]
  Intent -> Dialog [label="dialog intent"]
  Intent -> LLM    [label="IT question"]
  BkOT   -> Bot
  BkJB   -> Bot
  BkST   -> Bot
  Dialog -> Bot [label="scripted reply"]
  LLM    -> Bot
}}""",

    6: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  PII     [label="PII Detector\\n(Python Action)\\nsystematic — every msg"  fillcolor="#FDEBD0"]
  Urgency [label="Urgency Detector\\n(Python Action)\\nsystematic — every msg" fillcolor="#FDEBD0"]
  BkPII   [label="Block:\\nPII Found" fillcolor="#FADBD8"]
  Warn    [label="Warn: Urgent!\\nthen continue" fillcolor="#FEF9E7"]
  Intent  [label="Intent Check\\n(LLM Call 1)"  fillcolor="#FEF9E7"]
  LLM     [label="LLM Answer\\n(LLM Call 2)"   fillcolor="#D5F5E3"]
  {_BOT}

  User    -> PII     [label="every msg"]
  PII     -> BkPII   [label="PII found → stop"]
  PII     -> Urgency [label="clean"]
  Urgency -> Warn    [label="urgent"]
  Urgency -> Intent  [label="normal"]
  Warn    -> Intent  [label="continue"]
  Intent  -> LLM     [label="allowed"]
  BkPII   -> Bot
  Intent  -> Bot     [label="rail fired"]
  LLM     -> Bot
}}""",

    7: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  Intent   [label="Intent Check\\n(LLM Call 1)"           fillcolor="#FEF9E7"]
  LLM      [label="LLM Answer\\n(LLM Call 2)"            fillcolor="#D5F5E3"]
  OutRail  [label="Output Sanitizer\\n(Python Action)\\nsystematic — every response" fillcolor="#FDEBD0"]
  Withheld [label="Response\\nWithheld"                   fillcolor="#FADBD8"]
  {_BOT}

  User    -> Intent
  Intent  -> LLM     [label="allowed"]
  LLM     -> OutRail [label="every response"]
  OutRail -> Withheld [label="credential /\\nexploit found"]
  OutRail -> Bot      [label="clean"]
  Withheld -> Bot     [label="safe message"]
}}""",

    8: f"""digraph {{
  rankdir=LR
  {_COMMON}
  {_USER}
  InjDetect [label="Injection Detector\\n(Python @action)\\nregex scan — every msg" fillcolor="#FDEBD0"]
  Sanitize  [label="Content Sanitizer\\n(Python @action)\\nstrips injection payloads" fillcolor="#FDEBD0"]
  BkInj     [label="Block:\\nInjection Detected" fillcolor="#FADBD8"]
  Intent    [label="Intent Check\\n(LLM Call 1)" fillcolor="#FEF9E7"]
  LLM       [label="LLM Answer\\n(LLM Call 2)"  fillcolor="#D5F5E3"]
  LeakCheck [label="System Prompt\\nLeak Detector\\n(Python @action)\\nevery response" fillcolor="#FDEBD0"]
  OutSan    [label="Output Sanitizer\\n(Python @action)\\ncredentials/exploits" fillcolor="#FDEBD0"]
  Withheld  [label="Response\\nWithheld" fillcolor="#FADBD8"]
  {_BOT}

  User       -> InjDetect [label="every msg"]
  InjDetect  -> BkInj     [label="injection found → stop"]
  InjDetect  -> Sanitize  [label="patterns found"]
  InjDetect  -> Intent    [label="clean"]
  Sanitize   -> Intent    [label="sanitized content"]
  BkInj      -> Bot       [label="blocked message"]
  Intent     -> LLM       [label="allowed"]
  LLM        -> LeakCheck [label="every response"]
  LeakCheck  -> Withheld  [label="system prompt leaked"]
  LeakCheck  -> OutSan    [label="no leak"]
  OutSan     -> Withheld  [label="credential/exploit found"]
  OutSan     -> Bot       [label="clean"]
  Withheld   -> Bot       [label="safe message"]
}}""",
}


def get_diagram(exp_num: int) -> str:
    return DIAGRAMS.get(exp_num, "")
