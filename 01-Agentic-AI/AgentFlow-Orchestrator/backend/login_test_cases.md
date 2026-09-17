# Automated Test Cases for Login Page

## Table of Contents
1. [Functional Test Cases](#functional-test-cases)
2. [Security Test Cases](#security-test-cases)
3. [Usability & Accessibility Test Cases](#usability--accessibility-test-cases)
4. [Performance Test Cases](#performance-test-cases)
5. [Negative & Edge‑Case Test Cases](#negative--edge-case-test-cases)

---

## Functional Test Cases
| ID | Title | Description | Preconditions | Test Steps | Expected Result | Owner |
|----|-------|-------------|--------------|-----------|-----------------|-------|
| FT‑001 | Valid Login with Email | Verify that a user can log in with a valid email and password. | User account exists and is active. | 1. Navigate to login page. 2. Enter registered email. 3. Enter correct password. 4. Click **Login**. | User is redirected to the dashboard/home page and a welcome message is displayed. | QA |
| FT‑002 | Valid Login with Username | Verify login with a valid username (if supported). | User account exists with username. | Same as FT‑001 but use username field. | Successful login as above. | QA |
| FT‑003 | Remember Me Functionality | Verify that the **Remember Me** checkbox persists the session across browser restarts. | User account exists. | 1. Check **Remember Me**. 2. Log in successfully. 3. Close browser. 4. Re‑open browser and navigate to the site. | User remains logged in without re‑entering credentials. | QA |
| FT‑004 | Forgot Password Link Navigation | Verify that clicking **Forgot Password** navigates to the password‑reset page. | None | 1. Click **Forgot Password** link. | Password‑reset page loads with email input. | QA |
| FT‑005 | Show/Hide Password Toggle | Verify that the eye‑icon toggles password visibility. | None | 1. Type password. 2. Click eye‑icon. | Password characters become visible; clicking again hides them. | QA |
| FT‑006 | Logout Functionality | Verify that a logged‑in user can log out successfully. | User is logged in. | 1. Click **Logout** button/menu item. | Session ends, user is redirected to login page; protected pages are inaccessible. | QA |

---

## Security Test Cases
| ID | Title | Description | Preconditions | Test Steps | Expected Result | Owner |
|----|-------|-------------|--------------|-----------|-----------------|-------|
| ST‑001 | Invalid Login – Wrong Password | Ensure that login fails with an incorrect password. | Valid user account. | 1. Enter correct email. 2. Enter wrong password. 3. Click **Login**. | Error message *"Invalid username or password"* displayed; no login occurs. | QA |
| ST‑002 | Invalid Login – Non‑existent Account | Ensure login fails for an email that is not registered. | None | 1. Enter unregistered email. 2. Enter any password. 3. Click **Login**. | Same error message as ST‑001; no account enumeration leak. | QA |
| ST‑003 | Brute‑Force Protection | Verify account lockout after a configurable number of failed attempts. | Account with known credentials. | 1. Attempt login with wrong password **N** times (e.g., 5). 2. On **N+1** attempt, use correct password. | Account is locked or captcha is presented; correct credentials are not accepted until lockout period expires. | QA |
| ST‑004 | SQL Injection Prevention | Ensure login fields are protected against classic SQL injection payloads. | None | 1. In email field enter `"' OR '1'='1"`. 2. Enter any password. 3. Click **Login**. | Login fails with generic error; no unauthorized access granted. | QA |
| ST‑005 | XSS Protection in Error Messages | Verify that error messages do not reflect raw input. | None | 1. Enter `<script>alert(1)</script>` as email. 2. Click **Login**. | Error message is escaped; no script execution occurs. | QA |
| ST‑006 | Secure Transmission (HTTPS) | Verify that login credentials are sent over HTTPS. | None | 1. Open developer tools → Network. 2. Perform a login. | Request URL scheme is `https://`; request payload not visible in plain‑text. | QA |
| ST‑007 | CSRF Protection | Verify that login form includes anti‑CSRF token and rejects requests without it. | None | 1. Capture login POST request. 2. Replay request without the CSRF token. | Server returns 403/400 error; login not processed. | QA |
| ST‑008 | Password Field Input Type | Ensure password input uses `type="password"` to mask characters. | None | Inspect the password input element. | `type="password"` attribute present. | QA |

---

## Usability & Accessibility Test Cases
| ID | Title | Description | Preconditions | Test Steps | Expected Result | Owner |
|----|-------|-------------|--------------|-----------|-----------------|-------|
| UT‑001 | Tab Order Navigation | Verify that users can navigate the form using **Tab** key in logical order. | None | Press **Tab** repeatedly from the top of the page. | Focus moves: Email → Password → Remember Me → Login → Forgot Password. | QA |
| UT‑002 | Screen Reader Labels | Verify that form fields have appropriate ARIA labels/readable text. | Screen reader installed. | Activate screen reader and focus each field. | Reader announces *"Email address, edit text"* and *"Password, edit text"*. | QA |
| UT‑003 | Responsive Layout | Verify that the login page renders correctly on various screen sizes. | None | Resize browser window or use device emulation (mobile, tablet, desktop). | Form remains centered, fields are fully visible, no overlap. | QA |
| UT‑004 | Error Message Clarity | Verify that validation messages are clear, concise, and positioned near the offending field. | None | Submit empty form. | Messages such as *"Email is required"* appear under the email field in red text. | QA |
| UT‑005 | Keyboard Submit | Verify that pressing **Enter** while focus is on password field triggers login. | None | Focus password field, press **Enter**. | Form submits and proceeds as if **Login** button clicked. | QA |
| UT‑006 | Password Strength Indicator (if present) | Verify that a visual cue appears when password meets criteria. | None | Type a weak password, then a strong one. | Indicator updates (e.g., red → green) accordingly. | QA |

---

## Performance Test Cases
| ID | Title | Description | Preconditions | Test Steps | Expected Result | Owner |
|----|-------|-------------|--------------|-----------|-----------------|-------|
| PT‑001 | Login Response Time | Verify that the login API responds within acceptable SLA (e.g., <2 seconds). | Load testing tool configured. | Simulate a single login request. | Response time ≤ 2 seconds under normal load. | QA |
| PT‑002 | Concurrent Login Load | Verify system stability under concurrent login attempts (e.g., 100 users). | Load testing tool. | Fire 100 simultaneous login requests with valid credentials. | No server errors (5xx); average response ≤ 3 seconds; success rate ≥ 95 %. | QA |
| PT‑003 | Spike Test | Verify behavior when login traffic spikes suddenly (e.g., 500 requests in 10 seconds). | Load testing tool. | Generate spike. | System remains responsive; no crashes; graceful degradation if limits are reached. | QA |

---

## Negative & Edge‑Case Test Cases
| ID | Title | Description | Preconditions | Test Steps | Expected Result | Owner |
|----|-------|-------------|--------------|-----------|-----------------|-------|
| NE‑001 | Empty Fields Submission | Verify that submitting without entering any data shows appropriate validation. | None | Click **Login** with both fields empty. | Errors: *"Email is required"* and *"Password is required"*. | QA |
| NE‑002 | Email Format Validation | Verify that incorrectly formatted emails are rejected before server call. | None | Enter `user@@domain` or `userdomain.com`. | Client‑side validation error: *"Enter a valid email address"*. | QA |
| NE‑003 | Excessively Long Input | Verify handling of input values exceeding typical length limits (e.g., 256+ characters). | None | Enter 300‑character string in email/password fields. | Either client‑side validation rejects input or server returns a controlled error (e.g., 400 Bad Request). | QA |
| NE‑004 | Special Characters in Password | Verify that allowed special characters are accepted and not sanitized incorrectly. | None | Use password `P@ssw0rd!#%&*`. | Login succeeds if password matches stored hash. |
| NE‑005 | Internationalized Email Addresses | Verify login works with Unicode email addresses (e.g., `用户@例子.公司`). | Account created with such email. | Attempt login using the Unicode address. | Successful login or appropriate error if not supported. |
| NE‑006 | Login with Disabled/Locked Account | Verify that disabled accounts cannot log in. | Admin disables the account. | Attempt login with correct credentials. | Message *"Your account has been disabled. Please contact support."* displayed. |
| NE‑007 | Session Expiration After Inactivity | Verify that an authenticated session expires after a defined idle period. | User logged in. | Remain idle for the timeout (e.g., 15 minutes). Then attempt to navigate to a protected page. | User is redirected to login page; session cookie is invalidated. |

---

## How to Use This Document
- Each test case is designed to be automatable using UI‑automation frameworks (Selenium, Cypress, Playwright) or API‑testing tools (Postman, RestAssured).  
- The **Test Steps** column provides a clear, repeatable sequence.  
- Expected results include both UI feedback and backend behavior where applicable.  
- Owners can be assigned to specific test suites (functional, security, etc.).

*Generated by **Login Test Case Creator** on *(2026‑08‑25)*.*
