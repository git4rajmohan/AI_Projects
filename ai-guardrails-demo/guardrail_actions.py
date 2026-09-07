import re
from typing import Optional
from nemoguardrails.actions import action


@action(is_system_action=True)
async def detect_pii_in_input(context: Optional[dict] = None):
    """Returns list of PII type names found, or empty list (falsy) if clean."""
    user_message = context.get("user_message", "") if context else ""

    patterns = {
        "email":       r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "phone":       r"\b(\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
        "ssn":         r"\b\d{3}-\d{2}-\d{4}\b",
        "api_key":     r"(api[_\s-]?key|token|secret)[:\s]+[A-Za-z0-9_\-]{10,}",
        "credit_card": r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",
    }
    found = [ptype for ptype, pat in patterns.items()
             if re.search(pat, user_message, re.IGNORECASE)]
    return found


@action(is_system_action=True)
async def classify_urgency(context: Optional[dict] = None):
    """Returns True if the message signals a production emergency."""
    msg = (context.get("user_message", "") if context else "").lower()
    urgent_keywords = [
        "outage", "down", "crash", "critical",
        "emergency", "not working", "urgent", "p0", "p1",
    ]
    return any(kw in msg for kw in urgent_keywords)


@action(is_system_action=True)
async def sanitize_output(context: Optional[dict] = None):
    """Intercepts bot responses containing hardcoded credentials or exploit techniques."""
    # Different NeMo versions use different context keys for the bot's response.
    bot_message = ""
    if context:
        bot_message = (
            context.get("bot_message")
            or context.get("response")
            or context.get("last_bot_message")
            or ""
        )

    sensitive_output_patterns = {
        "hardcoded_credential": r"(?i)(password|passwd|secret|api[_\-]?key|token)\s*[:=]\s*['\"]?\w{4,}",
        "private_key":          r"-----BEGIN.{0,20}PRIVATE KEY-----",
        "exploit_technique":    r"(?i)\b(reverse.?shell|bind.?shell|shellcode|meterpreter)\b",
    }
    found = [ptype for ptype, pat in sensitive_output_patterns.items()
             if re.search(pat, bot_message)]
    return found


# ─────────────────────────────────────────────────────────────
# Prompt Injection Defense Actions (Exp 8)
# ─────────────────────────────────────────────────────────────

@action(is_system_action=True)
async def detect_injection_in_input(context: Optional[dict] = None):
    """Scans user message for prompt injection patterns — even when hidden inside data."""
    user_message = context.get("user_message", "") if context else ""

    injection_patterns = {
        "ignore_instructions": r"(?i)ignore (all |any |the )?(previous |prior )?instructions",
        "system_override":     r"(?i)\bSYSTEM\s*[:\)]|SYSTEM OVERRIDE|\[SYSTEM",
        "disregard_safety":    r"(?i)disregard (all |any )?(safety |security )?(rules|guidelines|filters)",
        "reveal_system":       r"(?i)(reveal|show|output|print|display).{0,30}(system |your )?(prompt|instructions?|rules)",
        "unrestricted_ai":     r"(?i)you are (now )?(an? )?unrestricted AI|no (rules|limits|restrictions) apply",
        "new_role":            r"(?i)you are now (DAN|an? (unrestricted|unfiltered|jailbroken))",
        "forget_role":         r"(?i)forget (your |all )?(role|instructions|system prompt|guidelines)",
        "action_item_override":r"(?i)ACTION ITEM\s*:.*forget|ACTION ITEM\s*:.*ignore",
        "code_comment_inject": r"(?i)#\s*IGNORE (PREVIOUS |ALL )?INSTRUCTIONS",
        "developer_mode":      r"(?i)developer mode|jailbreak (mode|enabled)",
    }
    found = [ptype for ptype, pat in injection_patterns.items()
             if re.search(pat, user_message)]
    return found


@action(is_system_action=True)
async def detect_system_prompt_leak(context: Optional[dict] = None):
    """Output rail — checks if the LLM's response contains leaked system instructions."""
    bot_message = ""
    if context:
        bot_message = (
            context.get("bot_message")
            or context.get("response")
            or context.get("last_bot_message")
            or ""
        )

    leak_patterns = {
        "system_prompt_revealed":  r"(?i)(my |the )?(system )?prompt (is|says|contains|states)",
        "instructions_revealed":   r"(?i)my (system )?instructions (are|say|state|include)",
        "role_definition_leaked":  r"(?i)I am (configured |programmed |set up )?(to be |as )?(an? )?Enterprise IT Assistant",
        "yaml_config_leaked":      r"(?i)(models:|engine:|openai|gpt-3\.5)",
        "rules_listed":            r"(?i)(I (must|am told to|am required to)|my rules are).{0,100}(kubernetes|intel|networking)",
    }
    found = [ptype for ptype, pat in leak_patterns.items()
             if re.search(pat, bot_message)]
    return found


@action(is_system_action=True)
async def sanitize_injected_content(context: Optional[dict] = None):
    """Data sanitization — strips/flags known injection payloads from user message content."""
    user_message = context.get("user_message", "") if context else ""

    # Patterns that indicate injection payloads hidden in data
    sanitize_patterns = [
        # Strip "SYSTEM:" prefixes
        (r"(?i)\bSYSTEM\s*[:\)]\s*", "[REDACTED-SYSTEM-TAG] "),
        # Strip "[SYSTEM OVERRIDE]" blocks
        (r"(?i)\[SYSTEM OVERRIDE\][^\]]*", "[REDACTED-OVERRIDE]"),
        # Strip "ACTION ITEM: Forget/Ignore" patterns
        (r"(?i)ACTION ITEM\s*:\s*(forget|ignore)[^\n]*", "[REDACTED-ACTION-ITEM]"),
        # Strip "# IGNORE PREVIOUS INSTRUCTIONS" code comments
        (r"(?i)#\s*IGNORE (PREVIOUS |ALL )?INSTRUCTIONS[^\n]*", "# [REDACTED-INJECTION]"),
        # Strip "IMPORTANT SYSTEM MESSAGE:" prefixes
        (r"(?i)IMPORTANT SYSTEM MESSAGE\s*:\s*", "[REDACTED-SYSTEM-MESSAGE] "),
    ]

    sanitized = user_message
    flagged = False
    for pattern, replacement in sanitize_patterns:
        if re.search(pattern, sanitized):
            flagged = True
            sanitized = re.sub(pattern, replacement, sanitized)

    if flagged:
        # Return the sanitized message by setting it in context
        if context:
            context["user_message"] = sanitized
        return True  # injection detected and sanitized

    return False  # no injection found
