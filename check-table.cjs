const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  
  await page.goto('http://localhost:5173/auth');
  await page.waitForTimeout(2000);
  
  await page.goto('http://localhost:5173/aitutordashboard/studentanalysis');
  await page.waitForTimeout(5000);
  
  console.log('Current URL:', page.url());
  
  const tables = await page.$$('table');
  console.log('Found', tables.length, 'tables');
  
  if (tables.length === 0) {
    const title = await page.title();
    const bodyText = await page.innerText('body');
    console.log('Page title:', title);
    console.log('Body text:', bodyText.slice(0, 500));
  } else {
    for (let t_idx = 0; t_idx < tables.length; t_idx++) {
      const table = tables[t_idx];
      const rows = await table.$$('tbody tr');
      console.log(`\nTable ${t_idx+1}: ${rows.length} rows in tbody`);
      
      const headers = await table.$$('thead th');
      console.log(`  Header count: ${headers.length}`);
      
      for (let i = 0; i < Math.min(rows.length, 5); i++) {
        const row = rows[i];
        const cells = await row.$$('td, th');
        console.log(`  Row ${i+1}: ${cells.length} cells`);
        for (let j = 0; j < cells.length; j++) {
          const cell = cells[j];
          const colspan = await cell.getAttribute('colspan') || '1';
          const text = (await cell.innerText()).trim().replace(/\n/g, ' ');
          console.log(`    Cell ${j+1} (colspan=${colspan}): ${text.slice(0, 60)}`);
        }
      }
    }
  }
  
  await browser.close();
})();
