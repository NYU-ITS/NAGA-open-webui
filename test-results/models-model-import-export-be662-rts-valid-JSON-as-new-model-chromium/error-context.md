# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: models/model-import-export.mocked.spec.ts >> custom model import and export (mocked) >> imports valid JSON as new model
- Location: playwright/tests/models/model-import-export.mocked.spec.ts:80:2

# Error details

```
Error: Channel closed
```

```
Error: locator.setInputFiles: Target page, context or browser has been closed
Call log:
  - waiting for locator('#models-import-input')

```

```
Error: browserContext.close: Target page, context or browser has been closed
```