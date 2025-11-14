# JSONB Migration Fixes Summary

## ✅ Issue Fixed

**Error**: `function json_array_elements_text(jsonb) does not exist`

**Root Cause**: After converting `group.user_ids` from `JSON` to `JSONB` in migration `b2c3d4e5f6a7`, the code was still using `json_array_elements_text` which only works with `JSON` type.

**Fix Applied**: Updated `backend/open_webui/models/groups.py` to use `jsonb_array_elements_text` instead of `json_array_elements_text`.

---

## ✅ Verification Complete

### Files Checked:
1. ✅ `backend/open_webui/models/groups.py` - **FIXED**
2. ✅ `backend/open_webui/models/models.py` - Already using `jsonb_array_elements_text` correctly
3. ✅ `backend/open_webui/models/knowledge.py` - Already using `jsonb_array_elements_text` correctly
4. ✅ `backend/open_webui/models/prompts.py` - Already using `jsonb_array_elements_text` correctly
5. ✅ `backend/open_webui/models/tools.py` - Already using `jsonb_array_elements_text` correctly
6. ✅ `backend/open_webui/models/chats.py` - Using `json_array_elements_text` correctly (Chat.chat and Chat.meta are still JSON, not JSONB)

### Columns Converted to JSONB (in migration):
- ✅ `model.access_control`
- ✅ `knowledge.access_control`
- ✅ `prompt.access_control`
- ✅ `tool.access_control`
- ✅ `group.user_ids`

### Columns NOT Converted (still JSON):
- ✅ `Chat.chat` - Still JSON, using `json_array_elements` correctly
- ✅ `Chat.meta` - Still JSON, using `json_array_elements_text` correctly

---

## 📝 Code Changes

### File: `backend/open_webui/models/groups.py`

**Line 160**: Changed from:
```python
FROM json_array_elements_text("group".user_ids) AS user_id_elem
```

**To**:
```python
FROM jsonb_array_elements_text("group".user_ids) AS user_id_elem
```

---

## ✅ Status

**All JSON/JSONB function mismatches have been resolved.**

- ✅ No other files need updates
- ✅ All JSONB columns use `jsonb_*` functions
- ✅ All JSON columns use `json_*` functions
- ✅ Syntax validated
- ✅ Ready for deployment

---

## 🔍 Notes

1. **Redundant Casts**: The code uses `::jsonb` casts on expressions like `(access_control->'write'->'group_ids')::jsonb`. Since `access_control` is JSONB, the `->` operator already returns JSONB, so these casts are redundant but harmless (PostgreSQL treats them as no-ops).

2. **Chat Columns**: `Chat.chat` and `Chat.meta` were intentionally NOT converted to JSONB in the migration, so using `json_array_elements` and `json_array_elements_text` is correct for those columns.

3. **Function Mapping**:
   - `json_array_elements_text()` → Works with `JSON` type
   - `jsonb_array_elements_text()` → Works with `JSONB` type
   - `json_array_elements()` → Works with `JSON` type
   - `jsonb_array_elements()` → Works with `JSONB` type

