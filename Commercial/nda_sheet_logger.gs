// — NDA Submissions — Google Sheet Logger + Email Notification ————————————————
// SETUP INSTRUCTIONS:
//  1. Open your Google Sheet
//  2. Click Extensions → Apps Script
//  3. Delete any existing code, paste this entire file
//  4. Click Save, then Deploy → New Deployment
//     - Type: Web App
//     - Execute as: Me
//     - Who has access: Anyone
//  5. Click Deploy + copy the Web App URL
//  6. Replace the SHEET_WEBHOOK url in each NDA form with the new URL

const SHEET_NAME       = 'NDA Submissions';
const NOTIFY_EMAIL     = 'soldbyjl@gmail.com';
const SHEET_URL        = 'https://docs.google.com/spreadsheets/d/1zoxQTYIoJanbY-ljqnVUS3JUcGQwU6bCDFuAlfDWVIM/edit';

function doPost(e) {
  try {
    const data  = JSON.parse(e.postData.contents);
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
      sheet.getRange(1, 1, 1, 20).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }

    sheet.appendRow([
      data.timestamp    || '',
      data.property     || '',
      data.s1_role      || '', data.s1_brokerage || '', data.s1_name || '', data.s1_email || '',
      data.s1_address   || '', data.s1_city      || '', data.s1_province || '', data.s1_phone || '', data.s1_date || '',
      data.s2_role      || '', data.s2_brokerage || '', data.s2_name || '', data.s2_email || '',
      data.s2_address   || '', data.s2_city      || '', data.s2_province || '', data.s2_phone || '', data.s2_date || '',
    ]);

    // — Email notification ————————————————————————————————————————————————————
    const property  = data.property || 'Unknown Property';
    const timestamp = data.timestamp || new Date().toLocaleString('en-CA', { timeZone: 'America/Vancouver' });

    let buyerInfo = `Signer 1\nName: ${data.s1_name || '—'}\nEmail: ${data.s1_email || '—'}\nPhone: ${data.s1_phone || '—'}\nRole: ${data.s1_role || '—'}`;

    if (data.s2_name) {
      buyerInfo += `\n\nSigner 2\nName: ${data.s2_name || '—'}\nEmail: ${data.s2_email || '—'}\nPhone: ${data.s2_phone || '—'}\nRole: ${data.s2_role || '—'}`;
    }

    const subject = `NDA Signed — ${property}`;
    const body    = `Hi Jeff,\n\nA new NDA has been submitted.\n\nProperty: ${property}\nSubmitted: ${timestamp}\n\n${buyerInfo}\n\nView all submissions:\n${SHEET_URL}\n\n—\nJeff Lam | Sutton Group West Coast Realty`;

    const mailOptions = { name: 'Jeff Lam NDA System' };
    if (data.pdf_base64 && data.pdf_filename) {
      const pdfBytes = Utilities.base64Decode(data.pdf_base64);
      const pdfBlob  = Utilities.newBlob(pdfBytes, 'application/pdf', data.pdf_filename);
      mailOptions.attachments = [pdfBlob];
    }
    GmailApp.sendEmail(NOTIFY_EMAIL, subject, body, mailOptions);
    // ————————————————————————————————————————————————————————————————————————

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
