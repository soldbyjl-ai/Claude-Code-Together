// — Buyer Search Criteria — Google Sheet Logger + Email Notification ——————————
// Lives in the "BUYER_DATA" Apps Script attached to the buyer criteria sheet.
// TO UPDATE:
//  1. Open the project → replace all code with this file → Save
//  2. Deploy → Manage deployments → ✏️ Edit → Version: New version → Deploy
//     (keeps the same Web App URL, so buyer_search_form.html needs no change)
//  3. Approve Gmail access when prompted

const NOTIFY_EMAIL = 'soldbyjl@gmail.com';

function doPost(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getActiveSheet();
  var data = JSON.parse(e.postData.contents);

  sheet.appendRow([
    data.timestamp || new Date(),
    data.firstName,
    data.lastName,
    data.email,
    data.contactNumber,
    data.dwellingTypes ? data.dwellingTypes.join(', ') : '',
    data.budgetMin,
    data.budgetMax,
    data.beds,
    data.baths,
    data.kitchens,
    data.sqftMin,
    data.sqftMax,
    data.yearBuiltMin,
    data.yearBuiltMax,
    data.lotSizeMin || '',
    data.lotSizeMax || '',
    data.includedParking || '',
    data.maxMonthlyStrataFees || '',
    data.petRestrictions || '',
    data.searchType || '',
    data.selectedAreas ? data.selectedAreas.join(', ') : '',
    data.selectedNeighbourhoods || '',
    data.customBoundary || ''
  ]);

  // Email failure must never block the sheet row above
  try {
    sendBuyerNotification(data, ss.getUrl());
  } catch (err) {
    console.error('Buyer notification email failed: ' + err);
  }

  return ContentService.createTextOutput(JSON.stringify({ result: 'success' }))
    .setMimeType(ContentService.MimeType.JSON);
}

// — Test: select "testNotification" in the editor toolbar and click Run ———————
// Triggers the Gmail permission prompt and sends a sample email (no sheet row).
function testNotification() {
  sendBuyerNotification({
    firstName: 'Test', lastName: 'Buyer', email: NOTIFY_EMAIL, contactNumber: '(604) 555-1234',
    dwellingTypes: ['Detached'], budgetMin: '$1.5M', budgetMax: '$2M',
    beds: '3+', baths: '2+', searchType: 'Areas', selectedAreas: ['Burnaby North']
  }, SpreadsheetApp.getActiveSpreadsheet().getUrl());
}

// — Email notification ————————————————————————————————————————————————————————
function sendBuyerNotification(data, sheetUrl) {
  var join = function (v) { return Array.isArray(v) ? v.join(', ') : (v || ''); };
  var range = function (min, max) {
    if (!min && !max) return '';
    return (min || 'Any') + ' – ' + (max || 'Any');
  };

  var name = ((data.firstName || '') + ' ' + (data.lastName || '')).trim() || 'Unknown Buyer';
  var submitted = new Date().toLocaleString('en-CA', { timeZone: 'America/Vancouver' });

  var lines = [
    ['Name',             name],
    ['Email',            data.email],
    ['Phone',            data.contactNumber],
    ['',                 ''],
    ['Dwelling Types',   join(data.dwellingTypes)],
    ['Budget',           range(data.budgetMin, data.budgetMax)],
    ['Beds',             data.beds],
    ['Baths',            data.baths],
    ['Kitchens',         data.kitchens],
    ['Interior Sq Ft',   range(data.sqftMin, data.sqftMax)],
    ['Year Built',       range(data.yearBuiltMin, data.yearBuiltMax)],
    ['Lot Size (sq ft)', range(data.lotSizeMin, data.lotSizeMax)],
    ['Parking',          data.includedParking],
    ['Max Strata Fees',  data.maxMonthlyStrataFees],
    ['Pet Restrictions', data.petRestrictions],
    ['',                 ''],
    ['Search Type',      data.searchType],
    ['Areas',            join(data.selectedAreas)],
    ['Neighbourhoods',   data.selectedNeighbourhoods],
    ['Custom Boundary',  data.customBoundary]
  ];

  var details = lines
    .filter(function (l) { return l[0] === '' || (l[1] !== undefined && l[1] !== null && l[1] !== ''); })
    .map(function (l) { return l[0] === '' ? '' : l[0] + ': ' + l[1]; })
    .join('\n')
    .replace(/\n{3,}/g, '\n\n');

  var subject = 'Buyer Criteria Submitted — ' + name;
  var body = 'Hi Jeff,\n\nA new buyer search criteria form has been submitted.\n\n'
    + 'Submitted: ' + submitted + '\n\n'
    + details + '\n\n'
    + 'View all submissions:\n' + sheetUrl + '\n\n'
    + '—\nJeff Lam | Sutton Group West Coast Realty';

  var options = { name: 'Jeff Lam Buyer Criteria' };
  if (data.email) options.replyTo = data.email;
  GmailApp.sendEmail(NOTIFY_EMAIL, subject, body, options);
}
