# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: models/model-import-export.mocked.spec.ts >> custom model import and export (mocked) >> exports all models from list page
- Location: playwright/tests/models/model-import-export.mocked.spec.ts:71:2

# Error details

```
Error: Channel closed
```

```
Error: locator.click: Target page, context or browser has been closed
Call log:
  - waiting for getByRole('button', { name: 'Export Models' })

```

```
Error: browserContext.close: Target page, context or browser has been closed
```