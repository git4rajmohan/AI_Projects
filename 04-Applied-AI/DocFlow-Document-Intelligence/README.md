# DocFlow — AI Document Intelligence & Invoice Approval Engine

> Invoice/document processing where AI reads (OCR + structured LLM extraction with per-field confidence) but deterministic validation, policy rules and human review own the decisions.

**Design principle:** *AI reads, code decides, humans own risk.*

## 🎯 What This Project Demonstrates

- Document intelligence (OCR + structured extraction)
- Per-field confidence scoring
- Deterministic validation and policy engine
- Human-in-the-loop review
- Audit trail

## 🧠 AI / Technical Focus

- PyMuPDF text extraction with Tesseract OCR fallback
- LLM structured JSON extraction (OpenAI-compatible client for Ollama)
- Per-field confidence scoring feeding validation rules
- Pydantic v2 schema enforcement

## 🏗️ Architecture

```text
Invoice PDF / Image
        ↓
PyMuPDF Text Extraction
        ↓
Tesseract OCR Fallback
        ↓
LLM Structured JSON
        ↓
Per-field Confidence
        ↓
Deterministic Validation
        ↓
Policy Rules
        ↓
Human Review when Required
        ↓
Audit Trail
```

## 🔄 Workflow

*To be verified from code.*

## 🛠️ Technology Stack

| Area | Technology |
|---|---|
| LLM | OpenAI-compatible client (Ollama) |
| Backend | FastAPI |
| Frontend | Streamlit |
| Documents | PyMuPDF, Tesseract OCR, Pillow |
| Validation | Pydantic v2 |
| Testing | pytest |

*To be verified against requirements files during Phase 3.*

## ⭐ Key AI Engineering Concepts

- Document AI with confidence scoring
- Deterministic financial/business validation
- Human-in-the-loop approval
- Audit trail

## 🛡️ Safety / Reliability

- Deterministic validation + policy rules
- Human review when required
- Sample accuracy/review-time numbers, if present, are **sample/project evaluation results**, not general production performance claims.

## 🧪 Testing / Evaluation

*To be verified — pytest suite to be documented from code.*

## 🚀 How to Run

*To be verified from the project's actual instructions.*

## 📁 Project Structure

*To be verified after code is copied in.*

## 💡 Engineering Notes

*To be verified.*

## 🔍 How This Project Differs

Document AI combined with deterministic financial/business validation and approval policy.

## 🤖 AI-Assisted Development

This project was developed using AI-assisted coding workflows. Architecture, implementation decisions, testing, debugging and validation were reviewed and refined during development.