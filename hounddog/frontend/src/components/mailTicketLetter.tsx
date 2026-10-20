import { renderToStaticMarkup } from "react-dom/server";
import { QRCodeSVG } from "qrcode.react";
import { fmtDateTime } from "../dateUtils";
import { photoRotation, rotatedPhotoSrc } from "../photoRotation";

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
  photo_rotation?: number | null;
}

export interface MailRecipient {
  name: string;
  address: string;
}

const DEPT = "Moravian University Police Department";
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

export function openMailLetter(ticket: MailLetterTicket, recipient: MailRecipient): boolean {
  const origin = window.location.origin;
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
  const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "America/New_York" });
  const plate = `${ticket.plate}${ticket.plate_state ? ` (${ticket.plate_state})` : ""}`;
  const recipientHtml = [recipient.name, ...addressLines(recipient.address)].map(esc).join("<br/>");

  const w = window.open("", "_blank", "width=850,height=1000");
  if (!w) return false;
  w.document.write("<p style=\"font-family:sans-serif;padding:24px\">Preparing letter…</p>");

  rotatedPhotoSrc(photoUrl, photoRotation(ticket)).then((photoSrc) => {
  w.document.open();
  w.document.write(`<!DOCTYPE html>
<html>
<head>
<title>${esc(citationNo)} — Mail Notice</title>
<style>
  @page { size: letter; margin: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Georgia, "Times New Roman", serif; color: #111; background: #fff; }
  .page { position: relative; width: 8.5in; min-height: 11in; padding: 0.5in 0.6in; margin: 0 auto; }
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
  .stub { margin-top: 8px; border-top: 1.5px dashed #555; padding-top: 8px; font-family: -apple-system, "Segoe UI", Arial, sans-serif; font-size: 9.5pt; }
  .stub .cut { font-size: 8pt; color: #555; text-align: center; margin-bottom: 6px; }
  .stub table td { padding: 4px 8px; }
  @media screen { body { background: #e5e7eb; } .page { box-shadow: 0 0 8px rgba(0,0,0,.2); background: #fff; margin: 16px auto; } }
</style>
</head>
<body>
<div class="page">
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
      <img class="photo" src="${esc(photoSrc)}" onerror="this.style.display='none'" />
    </div>

    <div class="respond">
      <div>${qrSvg}</div>
      <div>
        <strong>Pay or appeal online</strong> — scan the code or visit:<br/>
        <span class="url">${esc(payUrl)}</span><div style="height:6px"></div>
        <strong>Pay by mail</strong> — send a check or money order for ${fine} with the stub below to:<br/>
        ${DEPT}, ${DEPT_STREET}, ${DEPT_CITY}<br/>
        Write citation # ${esc(citationNo)} on your check.<div style="height:6px"></div>
        Questions? Email ${DEPT_EMAIL}.
      </div>
    </div>

    <p class="court">Citations that are not paid or appealed may be referred to the local Magisterial District Court, which carries additional court costs and fees.</p>

    <div class="stub">
      <div class="cut">✂ - - - - - - - - Detach and return this portion with your payment - - - - - - - -</div>
      <table style="width:100%">
        <tr><td class="l">Citation #</td><td>${esc(citationNo)}</td><td class="l">Plate</td><td>${esc(plate)}</td></tr>
        <tr><td class="l">Name</td><td>${esc(recipient.name)}</td><td class="l">Amount due</td><td style="font-weight:700;">${fine}</td></tr>
      </table>
    </div>
  </div>
</div>
<script>
  const img = document.querySelector('.photo');
  let printed = false;
  const go = () => { if (!printed) { printed = true; window.print(); } };
  if (img && !img.complete) { img.onload = go; img.onerror = go; setTimeout(go, 3000); } else { go(); }
</script>
</body>
</html>`);
  w.document.close();
  });
  return true;
}
