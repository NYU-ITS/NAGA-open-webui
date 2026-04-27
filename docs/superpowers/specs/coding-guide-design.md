# Coding Guide Design Specification

**Date:** 2026-04-26  
**Scope:** Comprehensive coding reference guide for NAGA-open-webui developers  
**Audience:** New developers (onboarding) + Experienced developers (quick reference)

---

## Overview

Create a **Learning Path** structured coding guide that serves two audiences:
- **New developers:** Sequential learning path (Foundations → By-Layer → Cross-cutting)
- **Experienced developers:** Quick-reference card for immediate answers

This guide documents established patterns, standards, and decision-making frameworks for the SvelteKit (frontend) + TypeScript (middle layer) + Python (backend) stack, using proven patterns from the existing codebase.

---

## Document Structure & Content

### 1. Root Document: `docs/coding-guide/README.md`
**Purpose:** Navigation hub and orientation  
**Contents:**
- Project overview (what is NAGA-open-webui)
- Audience paths (new dev vs experienced dev)
- Quick links to each guide
- When to use each document

---

### 2. `QUICK-REFERENCE.md` (2 pages max)
**Purpose:** Experienced developers get answers in <2 minutes  
**Audience:** Team members who know the stack  
**Contents:**
- **Feature Checklist:** Steps for adding a new feature (7-10 items)
- **Role Check Decision:** Where to add authorization (frontend/middle/backend decision tree)
- **File Structure Template:** Boilerplate for new pages, components, API functions
- **Copy-Paste Code Patterns:**
  - API function template (fetch pattern)
  - Store usage pattern
  - Layout role-check pattern
  - Component template

---

### 3. `1-FOUNDATIONS.md`
**Purpose:** Establish mental model for new developers  
**Audience:** New to the codebase, may be new to SvelteKit  
**Contents:**

#### 3.1 Tech Stack Overview
- Frontend: SvelteKit 2.5.20, Svelte 4.2.18, TypeScript, TailwindCSS
- Middle Layer: TypeScript, fetch-based API client
- Backend: Python (FastAPI implied), REST endpoints
- Build: Vite, ESLint, Prettier, Vitest, Cypress

#### 3.2 What is NAGA-open-webui?
- Web application built on Open WebUI fork
- Group-based learning management with role-based access control
- Backend integration for AI services
- Feature set includes chat, workspace, admin capabilities, and specialized dashboards

#### 3.3 Mental Model: The Three Layers
Text explanation + diagram showing:
```
User Action (Frontend)
        ↓
Svelte Component → Store Update
        ↓
TypeScript API Function (middle layer)
        ↓
Fetch with Bearer token
        ↓
Python Backend Endpoint
        ↓
Database / AI Service
```

#### 3.4 The Data Flow Loop
Step-by-step example: "User adds a new group"
1. User clicks button in Svelte component
2. Component calls `createNewGroup()` from `src/lib/apis/groups/`
3. API function constructs fetch request with token
4. Backend returns group object or error
5. Frontend updates store and UI
6. Browser redirects or shows success toast

#### 3.5 Key Concepts (Explained Simply)
- **Stores:** Svelte's reactivity system (why they exist, how they work)
- **Routes:** SvelteKit file-based routing (why `(app)` groups exist)
- **API Functions:** Thin wrappers around fetch (why this pattern)
- **Role-Based Access:** Admin/Member/View/SuperAdmin (where each is checked)
- **Token Management:** Bearer tokens in headers (how authentication works)

#### 3.6 Folder Map
- `src/routes/` — Pages and layouts (SvelteKit routing)
- `src/lib/components/` — Reusable Svelte components
- `src/lib/apis/` — TypeScript API client functions
- `src/lib/stores/` — Svelte writable stores
- `src/lib/utils/` — Utility functions
- `src/lib/types/` — TypeScript type definitions

---

### 4. `2-FRONTEND-PATTERNS.md`
**Purpose:** How to build frontend pages and components  
**Contents:**

#### 4.1 Route Organization
- SvelteKit file-based routing explained
- What `(app)` layout groups mean
- How features organize their own route directories
- Layout component hierarchy (root → app → feature → page)

#### 4.2 Layout Components (`+layout.svelte`)
- When to use (shared navigation, top-level setup)
- Role checking in layouts (general pattern)
- Code: Typical layout structure with role check

#### 4.3 Page Components (`+page.svelte`)
- Data loading in `+page.ts` vs UI in `+page.svelte`
- Using stores for state
- Navigation with `goto()`
- Example: Creating a new feature page

#### 4.4 Component Structure (Reusable Components)
- Where to put them (`src/lib/components/`)
- Props interface
- Event handling (when to use events vs stores)
- Example: A simple button component

#### 4.5 Store Patterns
- When to use stores vs props
- Creating writable stores
- Subscribing in components (`$store` syntax)
- Persisting to localStorage
- Example: Selected group state (from dashboard)

#### 4.6 Styling
- TailwindCSS usage (no custom CSS in components)
- Dark mode (class-based, already implemented)
- Component scoped styles (when necessary)

#### 4.7 Common Gotchas
- Not using reactive statements (`$:`) when you should
- Forgetting to unsubscribe from stores (Svelte does this, but awareness)
- Direct DOM manipulation (don't do it)

---

### 5. `3-MIDDLE-LAYER.md`
**Purpose:** How the TypeScript API layer works  
**Contents:**

#### 5.1 API File Organization
- Where API functions live: `src/lib/apis/{resource}/`
- One resource = one directory (groups, users, models, tools, etc.)
- `index.ts` exports all functions for that resource

#### 5.2 The Fetch Pattern
Code walkthrough of existing pattern from `src/lib/apis/groups/index.ts`:
```typescript
export const createNewGroup = async (token: string, group: object) => {
    let error = null;
    const res = await fetch(`${WEBUI_API_BASE_URL}/groups/create`, {
        method: 'POST',
        headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ ...group })
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .catch((err) => {
            error = err.detail;
            console.log(err);
            return null;
        });

    if (error) {
        throw error;
    }

    return res;
};
```

**Why this pattern?**
- Promise chain: readable flow
- Error extraction: `err.detail` is backend convention
- Token passed as parameter: avoids global dependency
- Throws on error: caller decides how to handle

#### 5.3 Headers & Authentication
- Bearer token requirement
- Content-Type always `application/json`
- Authorization header format

#### 5.4 Error Handling
- Backend returns `{ detail: "error message" }`
- API layer extracts `err.detail`
- Throws so caller can catch with try/catch
- Example: Catching in a component

#### 5.5 Type Safety
- Optional: Adding TypeScript types for responses
- Where types live: `src/lib/types/`
- Improving the pattern: typed responses

#### 5.6 Creating a New API Function
- Template/checklist
- Example: Adding a new endpoint for a feature

---

### 6. `4-BACKEND-INTEGRATION.md`
**Purpose:** How frontend calls backend  
**Contents:**

#### 6.1 Backend Endpoint Shape
- Typical endpoint: `{WEBUI_API_BASE_URL}/resource/action`
- Methods: POST (create/update), GET (read), DELETE
- Response format: JSON object or array
- Error format: `{ detail: "error message" }`

#### 6.2 Understanding API Contracts
- What the backend expects (request body, headers)
- What the backend returns (response shape)
- How to know? Swagger docs (if available) or code inspection

#### 6.3 Token Management
- Token comes from `localStorage.token`
- Stored after login
- Passed to every API function

#### 6.4 Common Endpoints & Their Contracts
- `/groups/` — GET: fetch all groups
- `/groups/create` — POST: create group
- `/groups/id/{id}/update` — POST: update group
- User endpoints (auth, profile, superadmin check)
- AI Tutor endpoints (dashboard data)

#### 6.5 Debugging Backend Issues
- Check browser Network tab
- Log the fetch request and response
- Common errors: 401 (bad token), 403 (permission), 404 (not found)

---

### 7. `5-AUTHORIZATION.md` (Key for User's Request)
**Purpose:** Where and how to implement role-based access control  
**Contents:**

#### 7.1 Role Hierarchy
```
SuperAdmin (highest)
  ├── Can see all groups
  ├── Can edit any group
  └── Can manage users

Admin (per group)
  ├── Can edit their group
  └── Can manage group members

Member (per group)
  ├── Can access group resources
  └── Cannot edit group settings
```

#### 7.2 Where Roles Are Stored
- **Frontend:** `$user` store (from login response)
- **Backend:** Database (source of truth)
- **Checking:** API calls verify permissions

#### 7.3 Decision Tree: Where to Add a Role Check?

**Decision Tree:**
```
Is this a page or feature?
├── YES → Check in Layout Component (Frontend)
│   └── Prevents UX, fast feedback
│   └── Not a security boundary
│   └── Example: Redirect non-admin users from /admin
│
├── NO → Is the permission complex or requires DB data?
│   ├── YES → Check on Backend
│   │   └── Source of truth
│   │   └── Example: Can user delete this specific group?
│   │
│   └── NO → Can use Middle Layer OR Backend
│       └── Example: checkIfSuperAdmin API call
│       └── Or: Backend validates on actual operation
```

#### 7.4 Pattern 1: Frontend Role Check (in Layout)
**When:** Preventing non-admins from accessing restricted pages  
**Example:** Using `checkIfSuperAdmin()` from `src/lib/apis/users/` for permission verification

```typescript
import { checkIfSuperAdmin } from '$lib/apis/users';

onMount(async () => {
    // Simple role check using store
    if ($user?.role === 'user') {
        try {
            // For advanced checks, verify with backend
            const isSuperAdmin = await checkIfSuperAdmin(localStorage.token, $user.email);
            if (!isSuperAdmin) {
                goto('/');
            }
        } catch (err) {
            goto('/');
        }
    }
});
```

**Key points:**
- Happens in `onMount()` in layout component
- Uses `$user` store to check basic role
- Calls real API functions like `checkIfSuperAdmin()` for deeper verification
- Redirects if unauthorized
- **Not a security boundary** — backend must also check

#### 7.5 Pattern 2: Middle Layer Role Check (API Function)
**When:** Validating permission before calling backend  
**Example:** `checkIfSuperAdmin(token, email)` from `src/lib/apis/users/`

The pattern from actual codebase:
```typescript
export const checkIfSuperAdmin = async (token: string, email: string) => {
    let error = null;

    const res = await fetch(`${WEBUI_API_BASE_URL}/users/is-super-admin?email=${encodeURIComponent(email)}`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .catch((err) => {
            error = err.detail;
            return false;
        });

    if (error) {
        throw error;
    }

    return res;
};
```

**Key points:**
- Encapsulates permission logic in a reusable function
- Follows standard error handling pattern (extract err.detail, throw)
- Still not a security boundary — backend is final check

#### 7.6 Pattern 3: Backend Role Check (Source of Truth)
**When:** Protecting sensitive operations  
**Where:** Python backend endpoint validation

**Example backend check (conceptual):**
```python
# Backend validates group ownership
def update_group(group_id, data, current_user):
    group = db.get_group(group_id)
    if not (group.admin_id == current_user.id or current_user.is_superadmin):
        raise PermissionError("Not authorized")
    
    # Safe to proceed
    group.update(data)
```

**Key points:**
- Final validation happens here
- Even if frontend allows it, backend can reject
- Backend is source of truth

#### 7.7 Implementation Checklist for New Feature with Role Requirements
- [ ] Determine who should access (Admin? SuperAdmin? Everyone?)
- [ ] Add frontend role check in layout (UX/early feedback)
- [ ] Add API function call if needed for permission verification
- [ ] Ensure backend endpoint validates on operation (security)
- [ ] Test both authorized and unauthorized paths
- [ ] Document role requirements in code comments

#### 7.8 Common Mistakes
- Only checking frontend (user can bypass in dev tools)
- Not checking backend (false security)
- Checking in wrong place (middle layer when should be frontend)
- Forgetting to pass token to API function

---

### 8. `6-TESTING.md`
**Purpose:** How to test across layers  
**Contents:**

#### 8.1 Testing Stack
- Unit: Vitest
- Integration: Vitest (API layer)
- E2E: Cypress
- When to use each

#### 8.2 Unit Testing
- Utilities and pure functions
- Store behavior
- Example: Testing a Svelte store

#### 8.3 API Layer Testing
- Mocking fetch (or hitting test backend)
- Testing error handling
- Example: Testing `createNewGroup()`

#### 8.4 Component Testing
- Testing user interactions
- Mocking stores and API calls
- Example: Testing a button click

#### 8.5 E2E Testing with Cypress
- Testing full feature flows
- When authorization should be tested
- Example: User logs in → creates group → sees it in list

#### 8.6 Testing Authorization
- Frontend role check: unit test
- Backend role check: E2E test (prove user can't bypass)

---

### 9. `7-ERROR-HANDLING.md`
**Purpose:** How errors flow through the system  
**Contents:**

#### 9.1 Backend Error Format
- Backend returns: `{ detail: "Human-readable error message" }`
- Status codes: 400 (bad input), 401 (auth), 403 (forbidden), 404 (not found), 500 (server error)

#### 9.2 API Layer Error Handling
- Extracts `err.detail`
- Throws so component can catch
- Logs for debugging

#### 9.3 Frontend Error Display
- Component catches with try/catch
- Shows toast/error message to user
- Example: "Group creation failed: {error}"

#### 9.4 User-Facing vs Developer Errors
- User error: "Email already in use" (show to user)
- Dev error: "TypeError: cannot read property 'id'" (log, show generic message)

#### 9.5 Error Handling Checklist
- [ ] API function throws on error
- [ ] Component catches with try/catch
- [ ] Show user-friendly error message (toast)
- [ ] Log raw error for debugging
- [ ] Test error path in tests

---

### 10. `8-ANTI-PATTERNS.md`
**Purpose:** What to avoid and why  
**Contents:**

#### 10.1 Component Anti-Patterns
- **Too many responsibilities** — one component doing routing, data fetching, UI, styling
  - Fix: Split into smaller components
- **Props drilling** — passing data 5 levels deep
  - Fix: Use a store for shared state
- **Direct DOM manipulation** — `document.querySelector()` in Svelte
  - Fix: Use component state and bindings

#### 10.2 Store Anti-Patterns
- **Store for everything** — using stores for local component state
  - Fix: Component-level state for local concerns only
- **Untyped stores** — can't reason about shape
  - Fix: Add TypeScript types

#### 10.3 API Anti-Patterns
- **Mixing API logic with components** — fetch directly in component
  - Fix: Use API functions in `src/lib/apis/`
- **No error handling** — calling API without try/catch
  - Fix: Always handle errors in component

#### 10.4 Authorization Anti-Patterns
- **Frontend-only checks** — assuming frontend is secure
  - Fix: Backend validation is mandatory
- **Hardcoded role names** — spreading 'admin' strings everywhere
  - Fix: Create role constants or enum

#### 10.5 Why These Matter
- Maintainability: New devs understand code
- Testability: Isolated units are easier to test
- Security: Role checks at right boundaries
- Performance: Proper store usage avoids re-renders

---

## Document Characteristics

### Tone & Style
- **New dev focused:** Explain WHY not just WHAT
- **Experienced dev focused:** Quick examples, minimal explanation
- **Practical:** Show code from actual codebase
- **Non-prescriptive:** Document what IS, not ideals

### Code Examples
- All examples taken from actual codebase where possible
- Show minimal working example (not full file)
- Annotate WHY each line exists

### Cross-References
- Each document references related docs
- "See also" sections for jumping to related topics
- Decision trees point to implementation guides

---

## Out of Scope (Explicitly)

This guide does NOT cover:
- ~~Architectural refactoring~~ (tech debt cleanup can follow once patterns are documented)
- ~~Performance optimization techniques~~ (too context-specific)
- ~~Deployment or DevOps~~ (separate from coding patterns)
- ~~IDE/tool setup~~ (covered in README.md separately)

---

## File Locations

All documents live in: `docs/coding-guide/`

This creates a clear folder that future developers can find and use as a reference.

---

## Success Criteria

When complete, a new developer should be able to:
1. Read FOUNDATIONS.md and understand the architecture
2. Look up "where do I add a role check?" and get a clear answer
3. Find code examples for common patterns
4. Know what to avoid and why
5. Test their work using the testing guide

An experienced developer should be able to:
1. Open QUICK-REFERENCE.md and get answers in <2 minutes
2. Find the template for a new API function
3. Copy-paste patterns for new features

---

## Timeline & Next Steps

1. **Spec Review** (now) — User reviews this spec
2. **Implementation** — Create each .md file with outlined content
3. **Code Examples** — Extract/adapt from actual codebase
4. **Internal Review** — Read through for coherence
5. **Team Review** — Share with team for feedback
6. **Commit** — Save to git

---

## Open Questions / Decisions Needed

1. Should we include example code for the Python backend? (Currently scoped to frontend/middle layer)
2. Should we document any specific patterns from the AI Tutor Dashboard that are unique?
3. Any other coding standards or patterns not yet mentioned?