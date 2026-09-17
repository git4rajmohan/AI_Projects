# Project 3: Document Intelligence and Approval System

## 1. Project Overview

**Goal:** Build a document workflow that uses AI to understand
documents, validates extracted information, makes a controlled business
decision, and sends exceptions to a human reviewer.

**Possible use cases:** Invoice approval, contract review, insurance
claims, clinical prior authorization.

**Recommended use case: Invoice Approval**

Core flow:

**Extraction → Validation → Matching → Policy Decision → Human Review →
Approval/Rejection → Audit**

------------------------------------------------------------------------

## 2. Example Business Scenario

A company receives an invoice from a vendor.

The system should:

1.  Receive the invoice.
2.  Read the document.
3.  Extract structured fields.
4.  Validate the vendor and invoice data.
5.  Match the invoice against the purchase order.
6.  Apply the company's approval policy.
7.  Automatically approve safe cases.
8.  Send uncertain or high-risk cases to a human reviewer.
9.  Record an explainable audit trail.

Example:

> Invoice from ABC Supplier for ¥850,000 referencing PO-12345.

The system should determine:

-   Is the vendor valid?
-   Does the purchase order exist?
-   Do invoice line items match the PO?
-   Are quantities correct?
-   Are prices within tolerance?
-   Is this a duplicate invoice?
-   Does the total exceed an approval threshold?
-   Should it be approved or reviewed?

------------------------------------------------------------------------

## 3. End-to-End Workflow

``` text
Invoice Received
       ↓
OCR / Document Understanding
       ↓
AI Field Extraction
       ↓
Vendor + Line-Item Validation
       ↓
Invoice ↔ Purchase Order Match
       ↓
Optional Goods Receipt Match
       ↓
Deterministic Approval Policy
       ↓
   ┌───────────────┐
   │               │
Approve         Exception
   │               │
   │          Human Reviewer
   │               ↓
   │        Approve / Reject /
   │        Correct / Request Info
   │               │
   └───────┬───────┘
           ↓
Systems of Record
           ↓
Audit Trail
```

------------------------------------------------------------------------

## 4. Document Intelligence / Extraction

The system should handle:

-   PDF invoices
-   Scanned invoices
-   Photos of invoices
-   Different vendor templates
-   Poor-quality scans
-   Different languages or formats

### Fields to Extract

-   Vendor Name
-   Vendor ID
-   Invoice Number
-   Invoice Date
-   PO Number
-   Currency
-   Line Items
-   Product / Service Description
-   Quantity
-   Unit Price
-   Tax
-   Subtotal
-   Total Amount
-   Bank Account

Use structured output rather than free-form text.

Example:

``` json
{
  "vendor_name": "ABC Supplier",
  "invoice_number": "INV-10025",
  "invoice_date": "2026-09-15",
  "po_number": "PO-12345",
  "currency": "JPY",
  "total_amount": 850000,
  "confidence": 0.96
}
```

------------------------------------------------------------------------

## 5. Separate AI Work from Deterministic Control

This is one of the most important design principles.

### AI / Probabilistic Work

AI can help with:

-   Reading an ugly scan
-   Identifying vendor names
-   Understanding different invoice layouts
-   Extracting fields
-   Mapping invoice line items to PO items
-   Interpreting ambiguous content

### Deterministic Work

Normal application code should handle:

-   Total calculations
-   Tax calculations
-   Quantity checks
-   Price checks
-   Tolerance checks
-   Duplicate detection
-   Required-field checks
-   Vendor validation
-   Purchase-order existence
-   Approval thresholds
-   Business rules

### Key Principle

> **AI interprets. Code verifies.**

Do not allow an LLM to decide critical financial rules when
deterministic code can enforce them.

------------------------------------------------------------------------

## 6. Vendor Validation

Validate the vendor against the company's vendor master.

Checks:

-   Vendor exists
-   Vendor is active
-   Vendor ID matches
-   Invoice vendor name matches
-   Bank account is valid
-   Vendor is allowed for the purchase order

Example:

``` text
Invoice Vendor: ABC Supplier
Vendor Master: ABC Supplier
Vendor Status: Active
Vendor ID: V-10025

Result: PASS
```

------------------------------------------------------------------------

## 7. Line-Item Validation

Validate invoice line items against the purchase order.

Check:

-   Product/service
-   Quantity
-   Unit price
-   Currency
-   Tax
-   Total
-   Allowed tolerance

Example:

``` text
PO:
Product A
Quantity = 100
Unit Price = ¥1,000

Invoice:
Product A
Quantity = 100
Unit Price = ¥1,000

Result: MATCH
```

If the invoice quantity is 150 instead of 100, create an exception.

------------------------------------------------------------------------

## 8. Two-Way Matching

Start with:

``` text
Invoice
   ↕
Purchase Order
```

Compare:

-   Vendor
-   PO number
-   Line items
-   Quantity
-   Unit price
-   Total amount

Example:

``` text
Invoice Total = ¥850,000
PO Total      = ¥850,000

Result: MATCH
```

------------------------------------------------------------------------

## 9. Three-Way Matching

For a deeper implementation:

``` text
          Purchase Order
           ↙          ↘
      Invoice       Goods Receipt
```

Check:

1.  What was ordered?
2.  What was invoiced?
3.  What was actually received?

Example:

``` text
PO Quantity        = 100
Goods Received     = 100
Invoice Quantity   = 100

Result: MATCH
```

If the goods received quantity is 80 but the invoice quantity is 100,
flag the invoice.

------------------------------------------------------------------------

## 10. Approval Policy

Approval rules should be deterministic.

Example:

``` text
Invoice < ¥100,000
    → Auto approval if all checks pass

¥100,000–¥1,000,000
    → Manager approval

> ¥1,000,000
    → Finance approval
```

Other examples:

-   New vendor → additional verification
-   Changed bank account → mandatory human review
-   Duplicate invoice → reject/investigate
-   PO mismatch → exception
-   Low extraction confidence → human review

The LLM should not determine approval thresholds.

------------------------------------------------------------------------

## 11. Exception Handling

Create realistic failure cases.

### Duplicate Invoice

``` text
Invoice Number: INV-10025
Existing Invoice: INV-10025

Result: DUPLICATE
```

Do not automatically approve.

### Changed Bank Account

``` text
Vendor Master Bank Account: XXXX1234
Invoice Bank Account:       XXXX9876

Result: HIGH-RISK EXCEPTION
```

Require human verification.

### Missing Purchase Order

``` text
Invoice PO Number: PO-99999
PO System: PO not found

Result: EXCEPTION
```

### Quantity Mismatch

``` text
PO Quantity      = 100
Invoice Quantity = 150

Result: MISMATCH
```

### Unreadable Field

``` text
Invoice Total
OCR confidence = 0.42

Result: HUMAN REVIEW
```

------------------------------------------------------------------------

## 12. Human-in-the-Loop

A human should review:

-   Low-confidence extraction
-   High-value invoices
-   Changed bank accounts
-   Duplicate invoices
-   Significant PO mismatches
-   Unreadable critical fields
-   Other high-risk exceptions

### Reviewer Workflow

``` text
Exception
   ↓
Human Reviewer
   ↓
View Original Document
   ↓
Inspect Extracted Fields
   ↓
Inspect Validation Results
   ↓
Inspect PO Match
   ↓
Inspect Policy Decision
   ↓
Approve / Reject / Correct / Request Information
```

The reviewer should see the evidence behind the decision.

------------------------------------------------------------------------

## 13. Explainability

Every decision should explain:

### What was extracted?

``` text
Vendor: ABC Supplier
Invoice Total: ¥850,000
PO: PO-12345
```

### What was validated?

``` text
Vendor: PASS
Required fields: PASS
Duplicate check: PASS
Total calculation: PASS
```

### What was matched?

``` text
PO: MATCH
Quantity: MATCH
Unit Price: MATCH
```

### Which policy was applied?

``` text
Invoice amount < ¥1M
Manager approval required
```

### Why was it approved?

``` text
All validation checks passed.
PO matched.
No duplicate detected.
Approval threshold satisfied.
```

### Who approved it?

Record:

-   Reviewer
-   Timestamp
-   Action
-   Comments

------------------------------------------------------------------------

## 14. Auditability

Maintain an audit trail for every invoice.

Recommended information:

``` text
Invoice ID
Document Version
Original Document
Extracted Fields
Extraction Confidence
Validation Results
PO Match Results
Policy Result
Exception Reason
Reviewer
Reviewer Action
Timestamp
Final Decision
```

This allows the company to reconstruct how every decision was made.

------------------------------------------------------------------------

## 15. Evaluation

Evaluate at multiple levels.

### Level 1 --- Field Extraction Accuracy

Measure:

-   Vendor extraction accuracy
-   Invoice number accuracy
-   PO number accuracy
-   Quantity accuracy
-   Total amount accuracy
-   Bank account accuracy

### Level 2 --- Match Accuracy

Measure:

-   Invoice-to-PO matching
-   Line-item matching
-   Quantity matching
-   Price matching
-   Three-way matching

### Level 3 --- Exception Recall

Measure whether dangerous cases are caught:

-   Duplicate invoice
-   Bank account change
-   Missing PO
-   Quantity mismatch
-   Total mismatch
-   Low-confidence extraction

### Level 4 --- False Approvals

Measure:

> How many invoices were incorrectly approved?

This is one of the most important metrics.

### Level 5 --- Latency

Measure:

``` text
Invoice received
       ↓
Final decision
```

Track average and worst-case processing time.

### Level 6 --- Review Time Saved

``` text
Manual review time
        -
AI-assisted review time
        =
Time saved
```

------------------------------------------------------------------------

## 16. Critical Evaluation Insight

A system can achieve:

``` text
98% field extraction accuracy
```

and still be dangerous.

If the missing 2% contains:

``` text
Bank Account
or
Total Amount
```

the financial risk can be high.

Therefore:

> **Evaluate critical fields separately and give high-risk errors more
> weight.**

------------------------------------------------------------------------

## 17. Business Value

Useful business metrics:

-   Review time saved
-   Faster invoice approval
-   Reduced manual data entry
-   Fewer duplicate payments
-   Fewer incorrect approvals
-   Faster exception resolution
-   Better auditability
-   Reduced operational workload

The goal is not simply:

> "The AI extracted 98% of fields."

The goal is:

> "The company can process invoices faster while reducing financial and
> compliance risk."

------------------------------------------------------------------------

## 18. Systems of Record

Integrate with business systems:

``` text
Invoice Repository
       ↓
Document Intelligence
       ↓
Vendor Master
       ↓
Purchase Order System
       ↓
Goods Receipt System
       ↓
ERP / Accounting System
       ↓
Approval System
```

The AI application should work with the company's systems of record
rather than becoming the system of record itself.

------------------------------------------------------------------------

## 19. Suggested Technology Architecture

### Frontend

-   React
-   Streamlit
-   Simple HTML/JavaScript

Recommended portfolio implementation:

**React + TypeScript**

### Backend

**Python + FastAPI**

### Document Processing

Possible technologies:

-   OCR
-   PyMuPDF
-   Tesseract
-   PaddleOCR
-   Document AI models
-   Vision-capable local LLM

### AI

Use AI for:

-   Document understanding
-   Field extraction
-   Layout interpretation
-   Line-item matching suggestions

For local experimentation:

-   Ollama
-   Open-source vision-capable models

### Database

-   PostgreSQL for production-style implementation
-   SQLite for a simple demo

Store:

-   Invoices
-   Vendors
-   Purchase Orders
-   Goods Receipts
-   Extracted fields
-   Validation results
-   Exceptions
-   Approval decisions
-   Audit events

------------------------------------------------------------------------

## 20. Architecture

``` text
                    INVOICE
                       ↓
             OCR / Document AI
                       ↓
              AI Field Extraction
                       ↓
        ┌──────────────┴──────────────┐
        ↓                             ↓
 Vendor Validation              Line-Item Validation
        ↓                             ↓
        └──────────────┬──────────────┘
                       ↓
              Invoice ↔ PO Match
                       ↓
          Optional Goods Receipt Match
                       ↓
           Deterministic Policy Engine
                       ↓
                 ┌─────┴─────┐
                 ↓           ↓
              APPROVE     EXCEPTION
                 ↓           ↓
                 │      HUMAN REVIEW
                 │           ↓
                 │     Approve / Reject /
                 │     Correct / Request Info
                 │           ↓
                 └─────┬─────┘
                       ↓
              Systems of Record
                       ↓
                  Audit Trail
```

------------------------------------------------------------------------

## 21. Key Design Principle

  Responsibility               Recommended Approach
  ---------------------------- -------------------------
  Understand document          AI
  Extract fields               AI
  Interpret ambiguous layout   AI
  Suggest line-item mapping    AI
  Verify totals                Deterministic code
  Check tolerance              Deterministic code
  Detect duplicates            Deterministic code
  Validate vendor              Deterministic code
  Enforce approval threshold   Deterministic code
  Review high-risk exception   Human
  Record final decision        System of record
  Audit decision               Application + audit log

------------------------------------------------------------------------

## 22. Recommended Demo Flow

### Demo 1 --- Normal Invoice

``` text
Upload invoice
   ↓
Extract fields
   ↓
Validate
   ↓
Two-way match
   ↓
Policy check
   ↓
Approve
```

### Demo 2 --- Quantity Mismatch

``` text
Upload invoice
   ↓
Extract
   ↓
PO quantity mismatch
   ↓
Exception
   ↓
Human review
```

### Demo 3 --- Duplicate Invoice

``` text
Upload invoice
   ↓
Extract invoice number
   ↓
Duplicate detected
   ↓
Block automatic approval
   ↓
Human investigation
```

### Demo 4 --- Changed Bank Account

``` text
Upload invoice
   ↓
Vendor validation
   ↓
Bank account mismatch
   ↓
HIGH-RISK EXCEPTION
   ↓
Human verification
```

### Demo 5 --- Low Confidence

``` text
Poor-quality scan
   ↓
AI extraction confidence = low
   ↓
Human review
   ↓
Correct field
   ↓
Resume workflow
```

------------------------------------------------------------------------

## 23. What Makes This an Enterprise AI Project?

This project demonstrates:

-   AI document understanding
-   Structured outputs
-   Deterministic validation
-   Business-rule enforcement
-   Two-way / three-way matching
-   Human-in-the-loop
-   Explainability
-   Auditability
-   Integration with systems of record
-   Risk-aware evaluation
-   Operational metrics
-   Business-value measurement

------------------------------------------------------------------------

## 24. FD Signal

The strongest signal from this project is:

> **You can build AI inside a high-stakes workflow while maintaining
> control, accountability, and measurable business value.**

The design demonstrates:

``` text
AI
 ↓
Probabilistic understanding

Code
 ↓
Deterministic verification

Human
 ↓
High-risk decision

System of Record
 ↓
Final business action

Audit
 ↓
Accountability
```

------------------------------------------------------------------------

## 25. Key Lesson

> **Document AI = Extraction + Validation + Matching + Policy + Human
> Review + Auditability**

### Most Important Rule

> **Do not stop at extraction. The real business value is in the MATCH
> and the DECISION.**

### Final Engineering Principle

> **AI can interpret uncertain document content, but deterministic code
> must protect critical business rules and humans must control high-risk
> exceptions.**
