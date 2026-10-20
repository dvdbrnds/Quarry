import { renderToStaticMarkup } from "react-dom/server";
import { QRCodeSVG } from "qrcode.react";
import { fmtDateTime } from "../dateUtils";

export interface MailLetterTicket {
  id: string;
  ticket_number: string | null;
  plate: string;
  plate_state?: string | null;
  lot: string;
  violation_type: string;
  additional_violations: { code: string; label: string; fine: string }[] | null;
  fine_amount: string;
  issued_at: string;
  status: string;
  ticket_category: string;
  location_text: string | null;
  vehicle_description: string | null;
  officer_name: string | null;
  officer_id: string;
  photo_url: string | null;
}

export interface MailRecipient {
  name: string;
  address: string;
}

const DEPT = "Moravian University Parking Authority";
const DEPT_STREET = "119 West Greenwich Street";
const DEPT_CITY = "Bethlehem, PA 18018";
const DEPT_EMAIL = "campuspolice@moravian.edu";

function esc(s: string | null | undefined): string {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

function titleCase(code: string): string {
  return code.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** "123 Main St, Bethlehem, PA 18018" -> ["123 Main St", "Bethlehem, PA 18018"]; explicit line breaks win. */
export function addressLines(address: string): string[] {
  const trimmed = address.trim();
  if (!trimmed) return [];
  if (trimmed.includes("\n")) return trimmed.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const idx = trimmed.indexOf(",");
  return idx > 0 ? [trimmed.slice(0, idx).trim(), trimmed.slice(idx + 1).trim()] : [trimmed];
}

const STYLES = `
  @page { size: letter; margin: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Georgia, "Times New Roman", serif; color: #111; background: #fff; }
  .page { position: relative; width: 8.5in; min-height: 11in; padding: 0.5in 0.6in; margin: 0 auto; break-after: page; }
  .page:last-child { break-after: auto; }
  .return { font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.35; }
  .return strong { font-size: 11pt; }
  .recipient { position: absolute; top: 2.05in; left: 0.875in; width: 3.75in; height: 1.1in;
               font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 11pt; line-height: 1.35; text-transform: uppercase; }
  .meta { position: absolute; top: 2.05in; right: 0.6in; text-align: right; font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.5; }
  .body { margin-top: 2.75in; }
  h1 { font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 14pt; letter-spacing: 0.5px; color: #1a2744;
       border-bottom: 2px solid #1a2744; padding-bottom: 4px; margin-bottom: 8px; }
  p { font-size: 10pt; line-height: 1.4; margin-bottom: 8px; }
  .grid { display: flex; gap: 14px; margin: 8px 0; }
  table { border-collapse: collapse; font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 10pt; flex: 1; }
  td { border: 1px solid #ccc; padding: 3px 8px; vertical-align: top; }
  td.l { background: #f3f5f8; font-weight: 600; width: 1.35in; }
  .photo { width: 2.2in; max-height: 2.1in; object-fit: cover; border: 1px solid #ccc; }
  .respond { display: flex; gap: 16px; align-items: center; border: 1.5px solid #1a2744; border-radius: 4px; padding: 8px 12px; margin: 8px 0;
             font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 9.5pt; line-height: 1.35; }
  .respond .url { font-family: Menlo, monospace; font-size: 9pt; word-break: break-all; }
  .court { font-size: 9.5pt; color: #7f1d1d; }
  .photo.flipped { transform: rotate(180deg); }
  .toolbar { position: sticky; top: 0; z-index: 1; display: flex; gap: 12px; align-items: center; justify-content: center; padding: 10px;
             background: #1a2744; color: #fff; font: 13px -apple-system, "Segoe UI", Arial, sans-serif; }
  .toolbar button { font: 600 13px -apple-system, "Segoe UI", Arial, sans-serif; padding: 7px 16px; border: 0; border-radius: 4px; cursor: pointer; }
  .toolbar button:disabled { opacity: 0.5; cursor: wait; }
  @media screen { body { background: #e5e7eb; } .page { box-shadow: 0 0 8px rgba(0,0,0,.2); background: #fff; margin: 16px auto; } .photo { cursor: pointer; } }
  @media print { .toolbar { display: none; } }
`;

function letterPage(ticket: MailLetterTicket, recipient: MailRecipient | null, origin: string, today: string): string {
  const payUrl = `${origin}/pay/${ticket.id}`;
  const photoUrl = ticket.photo_url ? `${origin}${ticket.photo_url}` : `${origin}/api/tickets/${ticket.id}/photo`;
  const qrSvg = renderToStaticMarkup(<QRCodeSVG value={payUrl} size={110} level="M" />);
  const citationNo = ticket.ticket_number || ticket.id.slice(0, 8).toUpperCase();
  const moving = ticket.ticket_category === "moving";
  const violations = [
    titleCase(ticket.violation_type),
    ...(ticket.additional_violations ?? []).map((v) => v.label || titleCase(v.code)),
  ];
  const fine = `$${Number(ticket.fine_amount || 0).toFixed(2)}`;
  const plate = `${ticket.plate}${ticket.plate_state ? ` (${ticket.plate_state})` : ""}`;
  const recipientHtml = recipient ? [recipient.name, ...addressLines(recipient.address)].filter(Boolean).map(esc).join("<br/>") : "";

  return `<div class="page">
  <div class="return"><strong>${DEPT}</strong><br/>${DEPT_STREET}<br/>${DEPT_CITY}</div>

  <div class="recipient">${recipientHtml}</div>
  <div class="meta">${esc(today)}<br/>Citation <strong>${esc(citationNo)}</strong><br/>Plate <strong>${esc(plate)}</strong></div>

  <div class="body">
    <h1>NOTICE OF ${moving ? "TRAFFIC" : "PARKING"} CITATION</h1>
    <p>On ${esc(fmtDateTime(ticket.issued_at))}, an officer of the ${DEPT} issued the ${moving ? "traffic" : "parking"} citation below
    to a vehicle registered to you. Our records show it has not been resolved. Please pay or appeal it using the options below.</p>

    <div class="grid">
      <table>
        <tr><td class="l">Citation #</td><td>${esc(citationNo)}</td></tr>
        <tr><td class="l">Date &amp; time</td><td>${esc(fmtDateTime(ticket.issued_at))}</td></tr>
        <tr><td class="l">License plate</td><td style="font-family:Menlo,monospace;letter-spacing:1px;font-weight:700;">${esc(plate)}</td></tr>
        ${ticket.vehicle_description ? `<tr><td class="l">Vehicle</td><td>${esc(ticket.vehicle_description)}</td></tr>` : ""}
        <tr><td class="l">Location</td><td>${esc(moving ? (ticket.location_text || ticket.lot || "—") : (ticket.lot || "—"))}</td></tr>
        <tr><td class="l">Violation${violations.length > 1 ? "s" : ""}</td><td>${violations.map(esc).join("<br/>")}</td></tr>
        <tr><td class="l">Issuing officer</td><td>${esc(ticket.officer_name || ticket.officer_id)}</td></tr>
        <tr><td class="l">Amount due</td><td style="font-weight:700;font-size:12pt;">${fine}</td></tr>
      </table>
      <img class="photo" src="${esc(photoUrl)}" title="Click to flip" />
    </div>

    <div class="respond">
      <div>${qrSvg}</div>
      <div>
        <strong>Pay or appeal online</strong> — payment is accepted online only. Scan the code or visit:<br/>
        <span class="url">${esc(payUrl)}</span><div style="height:6px"></div>
        Questions? Email ${DEPT_EMAIL}.
      </div>
    </div>

    <p class="court">Citations that are not paid or appealed may be referred to the local Magisterial District Court, which carries additional court costs and fees.</p>
  </div>
</div>`;
}

/**
 * Opens one window with a letter page per ticket. Print stays disabled until every photo has
 * loaded or failed, so bulk prints don't go out with blank photo slots.
 */
export function openMailLetters(items: { ticket: MailLetterTicket; recipient: MailRecipient | null }[], title = "Mail Notices"): boolean {
  if (items.length === 0) return false;
  const origin = window.location.origin;
  const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "America/New_York" });
  const single = items.length === 1;

  const w = window.open("", "_blank", "width=850,height=1000");
  if (!w) return false;
  w.document.write(`<!DOCTYPE html>
<html>
<head>
<title>${esc(title)}</title>
<style>${STYLES}</style>
</head>
<body>
<div class="toolbar">
  ${single ? `<button type="button" onclick="document.querySelector('.photo').classList.toggle('flipped')">Flip photo</button>` : `<span>Click any upside-down photo to flip it.</span>`}
  <button type="button" id="print" disabled onclick="window.print()">Loading photos…</button>
</div>
${items.map(({ ticket, recipient }) => letterPage(ticket, recipient, origin, today)).join("\n")}
<script>
  (function () {
    var imgs = Array.prototype.slice.call(document.querySelectorAll('.photo'));
    var btn = document.getElementById('print');
    var done = 0;
    function update() {
      if (done >= imgs.length) { btn.disabled = false; btn.textContent = ${JSON.stringify(single ? "Print" : `Print ${items.length} letters`)}; }
      else { btn.textContent = 'Loading photos ' + done + ' / ' + imgs.length + '…'; }
    }
    imgs.forEach(function (img) {
      img.addEventListener('click', function () { img.classList.toggle('flipped'); });
      function finish(failed) { if (img.dataset.done) return; img.dataset.done = '1'; if (failed) img.style.display = 'none'; done++; update(); }
      if (img.complete) finish(img.naturalWidth === 0);
      else { img.addEventListener('load', function () { finish(false); }); img.addEventListener('error', function () { finish(true); }); }
    });
    update();
  })();
</script>
</body>
</html>`);
  w.document.close();
  return true;
}

export function openMailLetter(ticket: MailLetterTicket, recipient: MailRecipient): boolean {
  const citationNo = ticket.ticket_number || ticket.id.slice(0, 8).toUpperCase();
  return openMailLetters([{ ticket, recipient }], `${citationNo} — Mail Notice`);
}
