// ── 935 Denman NDA — Google Sheet Logger ──────────────────────────────────
// SETUP INSTRUCTIONS:
//   1. Open your Google Sheet
//   2. Click Extensions → Apps Script
//   3. Delete any existing code, paste this entire file
//   4. Click Save, then Deploy → New Deployment
//      - Type: Web App
//      - Execute as: Me
//      - Who has access: Anyone
//   5. Click Deploy → copy the Web App URL
//   6. In nda_form.html, replace 'YOUR_APPS_SCRIPT_WEB_APP_URL' with that URL

const SHEET_NAME = 'NDA Submissions'; // tab name — will be created if it doesn't exist

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const ss    = SpreadsheetApp.getActiveSpreadsheet();
    let sheet   = ss.getSheetByName(SHEET_NAME);

    // Create sheet + header row on first run
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
      sheet.appendRow([
        'Timestamp',
        'Property',
        'S1 Role', 'S1 Brokerage', 'S1 Name', 'S1 Email',
        'S1 Address', 'S1 City', 'S1 Province', 'S1 Phone', 'S1 Date',
        'S2 Role', 'S2 Brokerage', 'S2 Name', 'S2 Email',
        'S2 Address', 'S2 City', 'S2 Province', 'S2 Phone', 'S2 Date',
      ]);
      // Bold the header row
      sheet.getRange(1, 1, 1, 20).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }

    sheet.appendRow([
      data.timestamp    || '',
      data.property     || '',
      data.s1_role      || '', data.s1_brokerage || '', data.s1_name  || '', data.s1_email || '',
      data.s1_address   || '', data.s1_city      || '', data.s1_province || '', data.s1_phone || '', data.s1_date || '',
      data.s2_role      || '', data.s2_brokerage || '', data.s2_name  || '', data.s2_email || '',
      data.s2_address   || '', data.s2_city      || '', data.s2_province || '', data.s2_phone || '', data.s2_date || '',
    ]);

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// Test via GET: visit the web app URL in browser to confirm it's live
function doGet() {
  return ContentService
    .createTextOutput('NDA Sheet Logger is running.')
    .setMimeType(ContentService.MimeType.TEXT);
}
