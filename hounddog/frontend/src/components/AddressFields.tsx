import { Input, Select } from "antd";

export interface MailingAddress {
  street: string;
  unit: string;
  city: string;
  state: string;
  zip: string;
}

export type AddressErrors = Partial<Record<keyof MailingAddress, string>>;

export const EMPTY_ADDRESS: MailingAddress = { street: "", unit: "", city: "", state: "", zip: "" };

const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
  "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP",
];

const STREET_RE = /^\d+[A-Za-z]?(-\d+[A-Za-z]?)?\s+([NSEW]\.?\s+)?[A-Za-z0-9][A-Za-z0-9.'\- ]*[A-Za-z][A-Za-z0-9.'\- ]*$/;
const PO_BOX_RE = /^(P\.?\s*O\.?\s*Box|Post\s+Office\s+Box)\s+\d+$/i;
const CITY_RE = /^[A-Za-z][A-Za-z.'\- ]*[A-Za-z]$/;
const ZIP_RE = /^\d{5}(-\d{4})?$/;

export function validateAddress(a: MailingAddress): AddressErrors {
  const errors: AddressErrors = {};
  const street = a.street.trim();
  if (!street) errors.street = "Required";
  else if (!STREET_RE.test(street) && !PO_BOX_RE.test(street)) errors.street = "Must be a house number and street name (e.g. 119 W Greenwich St) or PO Box 123";
  if (a.unit.trim().length > 20) errors.unit = "Too long";
  const city = a.city.trim();
  if (!city) errors.city = "Required";
  else if (!CITY_RE.test(city)) errors.city = "Letters only (e.g. Bethlehem)";
  if (!US_STATES.includes(a.state)) errors.state = "Required";
  const zip = a.zip.trim();
  if (!zip) errors.zip = "Required";
  else if (!ZIP_RE.test(zip)) errors.zip = "5 digits (or ZIP+4)";
  return errors;
}

export function isValidAddress(a: MailingAddress): boolean {
  return Object.keys(validateAddress(a)).length === 0;
}

/** Stored as "123 Main St Apt 2, Bethlehem, PA 18018" (street line, then city line after the first comma). */
export function formatAddress(a: MailingAddress): string {
  const street = [a.street.trim(), a.unit.trim()].filter(Boolean).join(" ");
  return `${street}, ${a.city.trim()}, ${a.state} ${a.zip.trim()}`;
}

const STATE_NAMES: Record<string, string> = {
  ALABAMA: "AL", ALASKA: "AK", ARIZONA: "AZ", ARKANSAS: "AR", CALIFORNIA: "CA", COLORADO: "CO", CONNECTICUT: "CT", DELAWARE: "DE",
  "DISTRICT OF COLUMBIA": "DC", FLORIDA: "FL", GEORGIA: "GA", HAWAII: "HI", IDAHO: "ID", ILLINOIS: "IL", INDIANA: "IN", IOWA: "IA",
  KANSAS: "KS", KENTUCKY: "KY", LOUISIANA: "LA", MAINE: "ME", MARYLAND: "MD", MASSACHUSETTS: "MA", MICHIGAN: "MI", MINNESOTA: "MN",
  MISSISSIPPI: "MS", MISSOURI: "MO", MONTANA: "MT", NEBRASKA: "NE", NEVADA: "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
  "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", OHIO: "OH", OKLAHOMA: "OK", OREGON: "OR",
  PENNSYLVANIA: "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", TENNESSEE: "TN", TEXAS: "TX", UTAH: "UT",
  VERMONT: "VT", VIRGINIA: "VA", WASHINGTON: "WA", "WEST VIRGINIA": "WV", WISCONSIN: "WI", WYOMING: "WY",
};
const STREET_SUFFIX_RE = /^(st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|ct|court|way|pl|place|pike|hwy|highway|cir|circle|ter|terrace|pkwy|parkway|trl|trail|aly|alley|sq|square|row|run|loop|xing)\.?$/i;
const UNIT_RE = /^(apt|unit|ste|suite|#|fl|floor|rm|room|bldg)\.?$/i;

/** Best-effort split of a stored address back into fields; anything unparseable lands in street. */
export function parseAddress(text: string | null | undefined): MailingAddress {
  const t = (text || "").replace(/\s*\n\s*/g, ", ").replace(/\s+/g, " ").trim();
  if (!t) return { ...EMPTY_ADDRESS };
  const zipMatch = t.match(/^(.*?)[,\s]+(\d{5}(?:-\d{4})?)(?:,?\s*USA?)?$/i);
  if (!zipMatch) return { ...EMPTY_ADDRESS, street: t };
  const zip = zipMatch[2];
  let rest = zipMatch[1].replace(/[,\s.]+$/, "");

  let state = "";
  const words = rest.split(/\s+/);
  const last = (n: number) => words.slice(-n).join(" ").replace(/^,|,$/g, "").replace(/\./g, "").toUpperCase();
  if (US_STATES.includes(last(1))) { state = last(1); words.splice(-1); }
  else if (STATE_NAMES[last(2)]) { state = STATE_NAMES[last(2)]; words.splice(-2); }
  else if (STATE_NAMES[last(1)]) { state = STATE_NAMES[last(1)]; words.splice(-1); }
  rest = words.join(" ").replace(/[,\s]+$/, "");

  let street = "";
  let unit = "";
  let city = "";
  if (rest.includes(",")) {
    const parts = rest.split(",").map((p) => p.trim()).filter(Boolean);
    city = parts.length > 1 ? parts.pop()! : "";
    const unitIdx = parts.findIndex((p, i) => i > 0 && (UNIT_RE.test(p.split(" ")[0]) || /^#/.test(p)));
    if (unitIdx > 0) unit = parts.splice(unitIdx, 1)[0];
    street = parts.join(" ");
  } else {
    const po = rest.match(/^((?:P\.?\s*O\.?\s*Box|Post Office Box)\s+\d+)\s+(.+)$/i);
    if (po) { street = po[1]; city = po[2]; }
    else {
      const w = rest.split(" ");
      let cut = -1;
      for (let i = w.length - 2; i >= 1; i--) {
        if (STREET_SUFFIX_RE.test(w[i])) { cut = i + 1; break; }
      }
      if (cut > 0) {
        let unitEnd = cut;
        if (unitEnd < w.length - 1 && UNIT_RE.test(w[unitEnd])) unitEnd += 2;
        else if (unitEnd < w.length - 1 && /^#\S+$/.test(w[unitEnd])) unitEnd += 1;
        street = w.slice(0, cut).join(" ");
        unit = w.slice(cut, unitEnd).join(" ");
        city = w.slice(unitEnd).join(" ");
      } else {
        street = rest;
      }
    }
  }
  const unitMatch = street.match(/^(\d.*?)\s+((?:apt|unit|ste|suite|fl|floor|rm|room|bldg)\.?\s*\S+|#\s*\S+)$/i);
  if (!unit && unitMatch) { street = unitMatch[1]; unit = unitMatch[2]; }
  return { street, unit, city, state, zip };
}

export function AddressFields({ value, onChange, errors, size }: {
  value: MailingAddress;
  onChange: (next: MailingAddress) => void;
  errors?: AddressErrors;
  size?: "small" | "middle";
}) {
  const set = (k: keyof MailingAddress) => (v: string) => onChange({ ...value, [k]: v });
  const field = (label: string, k: keyof MailingAddress, node: React.ReactNode, className = "") => (
    <div className={className}>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      {node}
      {errors?.[k] && <div className="text-xs text-red-600 mt-0.5">{errors[k]}</div>}
    </div>
  );
  return (
    <div className="grid grid-cols-6 gap-2">
      {field("Street number and name", "street",
        <Input size={size} value={value.street} status={errors?.street ? "error" : undefined}
          onChange={(e) => set("street")(e.target.value)} placeholder="119 W Greenwich St" />, "col-span-4")}
      {field("Apt / Unit", "unit",
        <Input size={size} value={value.unit} status={errors?.unit ? "error" : undefined}
          onChange={(e) => set("unit")(e.target.value)} placeholder="Apt 2B" />, "col-span-2")}
      {field("City / Town", "city",
        <Input size={size} value={value.city} status={errors?.city ? "error" : undefined}
          onChange={(e) => set("city")(e.target.value)} placeholder="Bethlehem" />, "col-span-3")}
      {field("State", "state",
        <Select size={size} value={value.state || undefined} status={errors?.state ? "error" : undefined} showSearch
          onChange={set("state")} placeholder="PA" options={US_STATES.map((s) => ({ value: s, label: s }))} className="w-full" />, "col-span-1")}
      {field("ZIP", "zip",
        <Input size={size} value={value.zip} status={errors?.zip ? "error" : undefined} maxLength={10}
          onChange={(e) => set("zip")(e.target.value.replace(/[^\d-]/g, ""))} placeholder="18018" />, "col-span-2")}
    </div>
  );
}
