# Super Admin Configuration

## Overview
Super admin email addresses are now centrally managed in **TWO locations only** - one for backend and one for frontend.

## How to Add/Remove Super Admins

### For Backend (Python)
**Edit:** `backend/open_webui/utils/super_admin.py`

```python
SUPER_ADMIN_EMAILS = [
    "sm11538@nyu.edu",
    "ms15138@nyu.edu", 
    "mb484@nyu.edu",
    "cg4532@nyu.edu",
    "ht2490@nyu.edu",
    "ps5226@nyu.edu"
]
```

This single list is imported and used across:
- `backend/open_webui/utils/workspace_access.py` - Workspace item access control
- `backend/open_webui/routers/groups.py` - Group management
- `backend/open_webui/routers/chats.py` - Chat access control
- `backend/open_webui/routers/auths.py` - First user signup validation
- `backend/open_webui/models/users.py` - User creation validation

### For Frontend (TypeScript/JavaScript)
**Edit:** `src/lib/constants.ts`

```typescript
export const SUPER_ADMIN_EMAILS = [
    'sm11538@nyu.edu',
    'ms15138@nyu.edu',
    'mb484@nyu.edu',
    'cg4532@nyu.edu',
    'ht2490@nyu.edu',
    'ps5226@nyu.edu'
];
```

This single constant is imported and used across:
- `src/lib/components/workspace/Tools/ToolkitEditor.svelte` - Tools in workspace
- `src/lib/components/workspace/Prompts/PromptEditor.svelte` - Prompts in workspace
- `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` - Knowledge base viewer
- `src/lib/components/workspace/Knowledge/CreateKnowledgeBase.svelte` - Knowledge base creator
- `src/lib/components/admin/Settings/Documents.svelte` - Admin document settings
- `src/lib/components/admin/Settings.svelte` - General admin settings

## Important Notes

1. **Keep Both Lists Synchronized**: Always ensure the email lists in both files match exactly
2. **Case Sensitivity**: Email comparisons are case-insensitive in the backend
3. **No Need to Edit Multiple Files**: Previously you had to edit 12 different files - now just 2!

## What Changed

### Before (Old System)
- Super admin emails were hardcoded in 12 different locations
- Adding/removing an admin required changing all 12 files
- Risk of inconsistency between files

### After (New System - Current)
- Super admin emails defined in 2 central locations
- Adding/removing an admin requires changing only 2 files
- All components import from these central sources
- Guaranteed consistency across the application

## Permissions Granted to Super Admins

Super admins have full access to:
- ✅ All workspace items (models, tools, prompts, knowledge bases)
- ✅ All groups (can view and manage all groups)
- ✅ All chats (including access to chats in any group)
- ✅ User management
- ✅ Admin settings (including restricted tabs)
- ✅ Document/file settings
- ✅ Can be the first user to sign up

## Example: Adding a New Super Admin

**Step 1:** Edit `backend/open_webui/utils/super_admin.py`
```python
SUPER_ADMIN_EMAILS = [
    "sm11538@nyu.edu",
    "ms15138@nyu.edu", 
    "mb484@nyu.edu",
    "cg4532@nyu.edu",
    "ht2490@nyu.edu",
    "ps5226@nyu.edu",
    "newadmin@nyu.edu"  # ← Add here
]
```

**Step 2:** Edit `src/lib/constants.ts`
```typescript
export const SUPER_ADMIN_EMAILS = [
    'sm11538@nyu.edu',
    'ms15138@nyu.edu',
    'mb484@nyu.edu',
    'cg4532@nyu.edu',
    'ht2490@nyu.edu',
    'ps5226@nyu.edu',
    'newadmin@nyu.edu'  // ← Add here
];
```

**Step 3:** Restart the application

Done! The new admin now has full super admin access across the entire application.

